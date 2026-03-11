# Asterisk PJSIP Realtime Provisioning API

A minimalist FastAPI micro-service that provisions SIP extensions into an **Asterisk 20 (LTS)** PBX using the **PJSIP Realtime** engine with a **SQLite3** backend.  A single API call creates the PJSIP objects **and** the Realtime dialplan entries — no SSH, no config-file editing, no `dialplan reload`.

Designed for a small 6-user PBX running on Alpine Linux in Docker, where Asterisk and this API share the same `pbx.db` file via a Docker volume.

---

## Architecture

```
┌──────────────┐         ┌──────────────────┐
│   SIP Phone  │◄──SIP──►│  Asterisk 20     │
│  (MP-114)    │         │  (PJSIP Realtime)│
└──────────────┘         └───────┬──────────┘
                                 │ reads
                                 ▼
                         ┌──────────────┐
                         │   pbx.db     │  ◄── shared Docker volume
                         │  (SQLite3)   │
                         └───────▲──────┘
                                 │ writes
                         ┌───────┴──────────┐
                         │  Provisioning API │
                         │  (FastAPI)        │
                         └──────────────────┘
```

### Database Tables

The API manages four Asterisk Realtime tables (defined in `schema.sql`):

| Table            | Purpose                                      |
|------------------|----------------------------------------------|
| `ps_auths`       | SIP authentication credentials (userpass)    |
| `ps_aors`        | Address-of-Record / registration bindings    |
| `ps_endpoints`   | Endpoint configuration (codecs, NAT, media)  |
| `extensions`     | Realtime dialplan — replaces `extensions.conf` |

The three `ps_*` rows share the same `id` (the username/extension number), which is the convention Asterisk's Realtime engine expects.  The `extensions` rows are keyed by `(context, exten, priority)` and are generated automatically when you provision an extension.

---

## Project Structure

```
asterisk-sqlite-api/
├── app/
│   ├── __init__.py       # Package marker
│   ├── database.py       # SQLite engine (10s timeout) & schema bootstrap
│   ├── models.py         # SQLModel ORM classes mapping to Asterisk tables
│   └── main.py           # FastAPI application & provisioning endpoints
├── schema.sql            # Authoritative DDL for Asterisk Realtime tables
├── requirements.txt      # Python dependencies
├── Dockerfile            # Alpine-based container image
└── README.md             # This file
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker (optional, for containerised deployment)

### Local Development

```bash
# Clone and enter the project
cd asterisk-sqlite-api

# Create a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Override the database path for local dev
export ASTERISK_DB_PATH="./pbx.db"

# Run the API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker build -t asterisk-provisioning-api .

docker run -d \
  --name provisioning-api \
  -p 8000:8000 \
  -v asterisk-data:/var/lib/asterisk \
  asterisk-provisioning-api
```

Make sure your Asterisk container mounts the same `asterisk-data` volume so both services share `pbx.db`.

---

## API Reference

### Health Check

```
GET /health
```

Returns `{"status": "ok"}`. Use as a Docker/Kubernetes liveness probe.

### Provision a SIP Extension

```
POST /provision/{username}
Content-Type: application/json

{
  "password": "s3cur3Pa55!",
  "context": "from-internal"
}
```

**Path Parameters:**

| Parameter  | Type   | Description                                    |
|------------|--------|------------------------------------------------|
| `username` | string | SIP username / extension number (e.g. `6001`)  |

**Body Parameters:**

| Field          | Type   | Required | Default          | Description                                       |
|----------------|--------|----------|------------------|---------------------------------------------------|
| `password`     | string | Yes      | —                | SIP auth password (min 8 chars)                   |
| `context`      | string | No       | `from-internal`  | Asterisk dialplan context                         |
| `ring_timeout` | int    | No       | `30`             | Seconds to ring before hanging up (5–120)         |

**Responses:**

| Status | Description                                      |
|--------|--------------------------------------------------|
| 201    | Extension provisioned successfully               |
| 409    | Extension already exists                         |
| 422    | Validation error (e.g. password too short)       |
| 500    | Database write failure                           |

**Example:**

```bash
curl -X POST http://localhost:8000/provision/6001 \
  -H "Content-Type: application/json" \
  -d '{"password": "MyStr0ngP@ss"}'
```

Response:

```json
{"status": "provisioned", "username": "6001"}
```

> **What happens behind the scenes:** this single call inserts rows into
> `ps_auths`, `ps_aors`, `ps_endpoints` **and** the `extensions` table.
> Asterisk picks up all four via Realtime — the extension is immediately
> dialable by other provisioned extensions without any reload.

### Remove a SIP Extension (including dialplan)

```
DELETE /provision/{username}
```

Removes all Realtime rows (auth, AOR, endpoint, **and** dialplan) for the given username. Asterisk will stop recognising the extension on its next Realtime lookup — no `pjsip reload` or `dialplan reload` needed.

**Example:**

```bash
curl -X DELETE http://localhost:8000/provision/6001
```

Response:

```json
{"status": "deprovisioned", "username": "6001"}
```

---

## NAT Traversal Settings

The API provisions endpoints with NAT-safe defaults, critical for devices like the **AudioCodes MP-114** sitting behind consumer routers:

| Setting           | Value | Why                                                                 |
|-------------------|-------|---------------------------------------------------------------------|
| `rtp_symmetric`   | `yes` | Send RTP back to the observed source IP:port, fixing one-way audio  |
| `force_rport`     | `yes` | Honour RFC 3581 rport even if the device doesn't request it         |
| `rewrite_contact` | `yes` | Rewrite Contact header with observed IP:port for in-dialog routing  |
| `direct_media`    | `no`  | Keep all RTP anchored on Asterisk (no reinvite) — essential for NAT |
| `dtmf_mode`       | `rfc4733` | Out-of-band DTMF via RTP events — most reliable for ATAs       |

---

## Concurrency & SQLite Locking

SQLite uses a file-level lock. Since Asterisk reads the database (via Realtime) while this API writes to it, contention is possible. Mitigations:

1. **10-second busy timeout** — the SQLAlchemy engine is configured with `timeout=10` in `connect_args`, so write attempts will retry for up to 10 seconds before raising "database is locked".
2. **WAL journal mode** — enabled at init time (`PRAGMA journal_mode=WAL`), allowing concurrent readers and a single writer without blocking each other.
3. **Small transaction scope** — each provisioning request opens a session, inserts three rows, and commits immediately.

For a 6-user PBX, this is more than sufficient. If you scale beyond ~50 concurrent users, consider migrating to PostgreSQL with `res_config_pgsql`.

---

## Asterisk Realtime Configuration

> **One-time setup** — these files live inside your Asterisk container
> (or Docker image).  Once configured, you never touch them again;
> everything else is managed through the API.

On the Asterisk side, ensure you have the following in your configuration:

**`/etc/asterisk/res_config_sqlite3.conf`:**

```ini
[pbx]
dbfile = /var/lib/asterisk/pbx.db
```

**`/etc/asterisk/sorcery.conf`:**

```ini
[res_pjsip]
endpoint=realtime,ps_endpoints
auth=realtime,ps_auths
aor=realtime,ps_aors
```

**`/etc/asterisk/extconfig.conf`:**

```ini
[settings]
ps_endpoints => sqlite3,pbx,ps_endpoints
ps_auths => sqlite3,pbx,ps_auths
ps_aors => sqlite3,pbx,ps_aors
; Realtime dialplan — Asterisk queries the 'extensions' table instead
; of reading extensions.conf for the 'from-internal' context.
extensions => sqlite3,pbx,extensions
```

**`/etc/asterisk/extensions.conf`:**

```ini
; Keep this file minimal.  The [from-internal] context is served
; entirely from the Realtime 'extensions' table via the API.
; You can still define static contexts here if needed.

[general]
static=yes
writeprotect=no

; Tell Asterisk to load 'from-internal' from Realtime.
; The API writes rows with context='from-internal' into the
; extensions table, so Asterisk will find them automatically.
[from-internal]
switch => Realtime/from-internal@extensions
```

The `switch => Realtime/...` directive is the key line.  It tells
Asterisk: *"when a call arrives in the `from-internal` context, look up
the dialled extension in the Realtime `extensions` table instead of in
this config file."*  Because `pbx_realtime` queries the database on
every call, new extensions provisioned via the API are dialable
immediately.

---

## Quick Start: Provision Two Extensions and Call

Once Asterisk is running with the configuration above and the API is up:

```bash
# 1. Provision two extensions
curl -X POST http://localhost:8000/provision/6001 \
  -H "Content-Type: application/json" \
  -d '{"password": "Ext6001Pass!"}'

curl -X POST http://localhost:8000/provision/6002 \
  -H "Content-Type: application/json" \
  -d '{"password": "Ext6002Pass!", "ring_timeout": 45}'

# 2. Verify the database (optional)
sqlite3 /var/lib/asterisk/pbx.db "SELECT * FROM extensions;"
# context         | exten | priority | app    | appdata
# from-internal   | 6001  | 1        | Dial   | PJSIP/6001,30,tT
# from-internal   | 6001  | 2        | Hangup |
# from-internal   | 6002  | 1        | Dial   | PJSIP/6002,45,tT
# from-internal   | 6002  | 2        | Hangup |

# 3. Register a SIP softphone as 6001, another as 6002.
#    Dial 6002 from 6001 — it rings, pick up, two-way audio.
```

No SSH into Asterisk.  No config files to edit.  No reloads.

---

## Interactive API Docs

FastAPI automatically generates interactive documentation:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## License

MIT