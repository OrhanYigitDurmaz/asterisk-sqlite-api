"""
Database engine configuration and schema bootstrap for the Asterisk
PJSIP Realtime SQLite backend.

Key design decisions
--------------------
* **10-second busy timeout** – Asterisk's Realtime engine holds brief
  read locks on the same ``pbx.db`` file.  A generous timeout prevents
  ``sqlite3.OperationalError: database is locked`` under light
  concurrent access (6 users, single-writer model).
* **check_same_thread=False** – required because FastAPI serves requests
  across multiple threads while SQLAlchemy may reuse the same underlying
  SQLite connection object.
* **Raw DDL bootstrap** – we execute ``schema.sql`` verbatim through the
  DBAPI connection so the table definitions stay in one authoritative
  place and are guaranteed identical to what Asterisk expects.
* **Environment override** – ``ASTERISK_DB_PATH`` lets you point at a
  local file during development/testing instead of the Docker volume
  default (``/var/lib/asterisk/pbx.db``).
"""

import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# The database lives on a Docker shared volume so both the Asterisk
# container and this API container see the same file.
# Override with ASTERISK_DB_PATH for local dev / tests.
_DB_PATH: str = os.environ.get("ASTERISK_DB_PATH", "/var/lib/asterisk/pbx.db")

# schema.sql sits at the repository root, one level above app/
_SCHEMA_PATH: Path = Path(__file__).resolve().parent.parent / "schema.sql"

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# connect_args:
#   timeout=10        → wait up to 10 s for the write lock instead of the
#                       default 5 s, reducing "database is locked" errors
#                       when Asterisk is reading while we write.
#   check_same_thread → False because ASGI servers are multi-threaded.
#
# pool_pre_ping=True  → emit a lightweight ``SELECT 1`` before handing out
#                       a connection so stale handles are recycled.
engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={
        "timeout": 10,
        "check_same_thread": False,
    },
    pool_pre_ping=True,
    echo=False,
)


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
def init_db() -> None:
    """
    Ensure the Asterisk Realtime tables exist in the SQLite database.

    We read the raw ``schema.sql`` file and execute it through the DBAPI
    connection so that:

    1. Table definitions are *exactly* what Asterisk expects (column
       names, types, defaults).  ``CREATE TABLE IF NOT EXISTS`` makes
       this call idempotent.
    2. SQLModel metadata is kept in sync with the physical schema for
       any future use of ``SQLModel.metadata.create_all()``.
    """
    # Read the authoritative DDL once.
    schema_sql: str = _SCHEMA_PATH.read_text(encoding="utf-8")

    # Execute raw DDL – ``executescript`` handles multiple statements
    # separated by semicolons and implicitly commits.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL;")
        # executescript is SQLite-specific; use raw DBAPI for multi-stmt DDL
        raw_conn = connection.connection  # unwrap to DBAPI connection
        raw_conn.executescript(schema_sql)  # type: ignore[union-attr]
        connection.commit()


def get_session():
    """
    FastAPI dependency that yields a SQLModel session.

    Usage::

        @app.post("/example")
        def example(session: Session = Depends(get_session)):
            ...

    The session is committed or rolled back automatically when the
    request handler returns or raises.
    """
    with Session(engine) as session:
        yield session
