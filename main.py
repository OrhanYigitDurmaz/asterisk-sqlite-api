import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("ASTERISK_DB_PATH", "/var/lib/asterisk/pbx.db")
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.close()
    yield


app = FastAPI(title="Asterisk PJSIP Provisioning API", lifespan=lifespan)


class CreateExtensionRequest(BaseModel):
    username: str
    password: str = Field(min_length=8)
    callerid: str


class RotatePasswordRequest(BaseModel):
    password: str = Field(min_length=8)


ENDPOINT_DEFAULTS = {
    "transport": "transport-ws",
    "context": "from-internal",
    "disallow": "all",
    "allow": "ulaw,alaw,opus",
    "webrtc": "yes",
    "dtmf_mode": "rfc4733",
    "rtp_symmetric": "yes",
    "force_rport": "yes",
    "rewrite_contact": "yes",
    "direct_media": "no",
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extensions", status_code=status.HTTP_201_CREATED)
def create_extension(body: CreateExtensionRequest):
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ps_endpoints WHERE id = ?", (body.username,)
        ).fetchone()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Extension already exists.")

        conn.execute(
            "INSERT INTO ps_auths (id, auth_type, username, password) VALUES (?, 'userpass', ?, ?)",
            (body.username, body.username, body.password),
        )
        conn.execute(
            "INSERT INTO ps_aors (id) VALUES (?)",
            (body.username,),
        )
        conn.execute(
            """INSERT INTO ps_endpoints
               (id, transport, aors, auth, context, disallow, allow, webrtc,
                dtmf_mode, rtp_symmetric, force_rport, rewrite_contact, direct_media, callerid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.username,
                ENDPOINT_DEFAULTS["transport"],
                body.username,
                body.username,
                ENDPOINT_DEFAULTS["context"],
                ENDPOINT_DEFAULTS["disallow"],
                ENDPOINT_DEFAULTS["allow"],
                ENDPOINT_DEFAULTS["webrtc"],
                ENDPOINT_DEFAULTS["dtmf_mode"],
                ENDPOINT_DEFAULTS["rtp_symmetric"],
                ENDPOINT_DEFAULTS["force_rport"],
                ENDPOINT_DEFAULTS["rewrite_contact"],
                ENDPOINT_DEFAULTS["direct_media"],
                body.callerid,
            ),
        )
        conn.execute(
            "INSERT INTO extensions (context, exten, priority, app, appdata) VALUES (?, ?, 1, 'Dial', ?)",
            (ENDPOINT_DEFAULTS["context"], body.username, f"PJSIP/{body.username},30,tT"),
        )
        conn.execute(
            "INSERT INTO extensions (context, exten, priority, app, appdata) VALUES (?, ?, 2, 'Hangup', '')",
            (ENDPOINT_DEFAULTS["context"], body.username),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "created",
        "username": body.username,
        "callerid": body.callerid,
    }


@app.put("/extensions/{username}/password")
def rotate_password(username: str, body: RotatePasswordRequest):
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ps_auths WHERE id = ?", (username,)
        ).fetchone()
        if not existing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Extension not found.")

        conn.execute(
            "UPDATE ps_auths SET password = ? WHERE id = ?",
            (body.password, username),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "rotated", "username": username}


@app.get("/extensions/{username}")
def get_extension(username: str):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM ps_endpoints WHERE id = ?", (username,)
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Extension not found.")
        return dict(row)
    finally:
        conn.close()


@app.delete("/extensions/{username}")
def delete_extension(username: str):
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ps_endpoints WHERE id = ?", (username,)
        ).fetchone()
        if not existing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Extension not found.")

        conn.execute("DELETE FROM ps_endpoints WHERE id = ?", (username,))
        conn.execute("DELETE FROM ps_aors WHERE id = ?", (username,))
        conn.execute("DELETE FROM ps_auths WHERE id = ?", (username,))
        conn.execute("DELETE FROM extensions WHERE exten = ?", (username,))
        conn.commit()
    finally:
        conn.close()

    return {"status": "deleted", "username": username}
