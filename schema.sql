-- ================================================================
-- Asterisk 20 PJSIP Realtime Schema (SQLite3)
--
-- These tables are queried directly by Asterisk's Realtime engine
-- via res_config_sqlite3.  Column names and types MUST match what
-- Asterisk expects — do not rename or remove columns.
--
-- All statements use IF NOT EXISTS so this file is idempotent.
-- ================================================================

-- 1. Authentication Table (Passwords)
CREATE TABLE IF NOT EXISTS ps_auths (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    auth_type VARCHAR(40) DEFAULT 'userpass',
    username VARCHAR(80),
    password VARCHAR(80),
    nonce_lifetime INTEGER,
    md5_cred VARCHAR(40),
    realm VARCHAR(40)
);

-- 2. AOR Table (Address of Record / Registration)
CREATE TABLE IF NOT EXISTS ps_aors (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    max_contacts INTEGER DEFAULT 1,
    remove_existing VARCHAR(10) DEFAULT 'yes',
    minimum_expiration INTEGER DEFAULT 60,
    default_expiration INTEGER DEFAULT 3600,
    maximum_expiration INTEGER DEFAULT 7200,
    qualify_frequency INTEGER DEFAULT 60,
    authenticate_qualify VARCHAR(10) DEFAULT 'no'
);

-- 3. Endpoints Table (The main logic)
CREATE TABLE IF NOT EXISTS ps_endpoints (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    transport VARCHAR(40) DEFAULT 'transport-udp',
    aors VARCHAR(200),
    auth VARCHAR(200),
    context VARCHAR(40) DEFAULT 'from-internal',
    disallow VARCHAR(200) DEFAULT 'all',
    allow VARCHAR(200) DEFAULT 'ulaw,alaw',
    direct_media VARCHAR(10) DEFAULT 'no',
    rtp_symmetric VARCHAR(10) DEFAULT 'yes',
    force_rport VARCHAR(10) DEFAULT 'yes',
    rewrite_contact VARCHAR(10) DEFAULT 'yes',
    dtmf_mode VARCHAR(20) DEFAULT 'rfc4733'
);

-- 4. Dialplan Extensions Table (Realtime Dialplan)
--
-- This table replaces static extensions.conf entries.  Asterisk's
-- pbx_realtime module queries it at call time, so new rows are
-- picked up immediately — no "dialplan reload" required.
--
-- Asterisk expects these exact column names (see Asterisk wiki:
-- "Realtime Dialplan").  Each row is one dialplan priority:
--
--   context  → dialplan context (e.g. "from-internal")
--   exten    → extension pattern or literal number
--   priority → execution order (1, 2, 3… or labels like "n")
--   app      → Asterisk application to execute (Dial, Answer, etc.)
--   appdata  → arguments passed to the application
--
-- Example rows for extension 6001:
--   ("from-internal", "6001", 1, "Dial",   "PJSIP/6001,30,tT")
--   ("from-internal", "6001", 2, "Hangup", "")
--
CREATE TABLE IF NOT EXISTS extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context VARCHAR(40) NOT NULL,
    exten VARCHAR(40) NOT NULL,
    priority INTEGER NOT NULL,
    app VARCHAR(40) NOT NULL,
    appdata VARCHAR(256) NOT NULL,
    UNIQUE(context, exten, priority)
);

-- Asterisk performs lookups by (context, exten) on every call.
-- This index ensures those queries are fast even as the table grows.
CREATE INDEX IF NOT EXISTS idx_extensions_context_exten
    ON extensions (context, exten);
