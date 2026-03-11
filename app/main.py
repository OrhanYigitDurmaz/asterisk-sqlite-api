"""
FastAPI provisioning API for Asterisk 20 PJSIP Realtime (SQLite backend).

This micro-service exposes endpoints that atomically create (or remove)
the PJSIP Realtime rows **and** the Realtime dialplan rows required for
a SIP extension to become immediately usable by Asterisk — no manual
config-file editing or ``dialplan reload`` required.

Designed for a minimalist 6-user PBX running on Alpine Linux in Docker.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session, init_db
from app.models import Extension, ProvisionRequest, PsAor, PsAuth, PsEndpoint


# ---------------------------------------------------------------------------
# Application lifespan – bootstrap the database on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Run ``init_db()`` once at startup so the Asterisk Realtime tables
    exist before we serve any provisioning requests.  Uses the modern
    lifespan protocol instead of the deprecated ``on_event`` hooks.
    """
    init_db()
    yield


app = FastAPI(
    title="Asterisk PJSIP Provisioning API",
    version="1.1.0",
    description=(
        "Provision SIP extensions into Asterisk 20 Realtime (SQLite).  "
        "Automatically creates PJSIP objects **and** Realtime dialplan "
        "entries so extensions can call each other without any manual "
        "configuration."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
def health_check() -> dict[str, str]:
    """Liveness probe for Docker / Kubernetes."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers – Realtime dialplan rows
# ---------------------------------------------------------------------------
def _create_dialplan_rows(
    session: Session,
    username: str,
    context: str,
    ring_timeout: int,
) -> None:
    """
    Insert the Realtime dialplan rows that let other extensions reach
    *username*.

    Generates the equivalent of this static ``extensions.conf`` block::

        [from-internal]
        exten => 6001,1,Dial(PJSIP/6001,30,tT)
         same =>      2,Hangup()

    Because Asterisk's ``pbx_realtime`` module queries the ``extensions``
    table on every call, these rows are picked up immediately — no
    ``dialplan reload`` needed.

    The ``tT`` Dial options allow both the caller (t) and the callee (T)
    to initiate an attended transfer via the configured feature code.
    """
    dial_row = Extension(
        context=context,
        exten=username,
        priority=1,
        app="Dial",
        appdata=f"PJSIP/{username},{ring_timeout},tT",
    )
    hangup_row = Extension(
        context=context,
        exten=username,
        priority=2,
        app="Hangup",
        appdata="",
    )
    session.add(dial_row)
    session.add(hangup_row)


def _delete_dialplan_rows(session: Session, username: str) -> None:
    """Remove all Realtime dialplan rows for *username* across every context."""
    rows = session.exec(select(Extension).where(Extension.exten == username)).all()
    for row in rows:
        session.delete(row)


# ---------------------------------------------------------------------------
# Provisioning endpoint
# ---------------------------------------------------------------------------
@app.post(
    "/provision/{username}",
    status_code=status.HTTP_201_CREATED,
    tags=["provisioning"],
    summary="Provision a new SIP extension",
    response_description="Confirmation with the provisioned username.",
)
def provision_user(
    username: str,
    body: ProvisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """
    Atomically create **ps_auths**, **ps_aors**, **ps_endpoints**, and
    **extensions** (dialplan) rows for *username* so the extension is
    immediately available to Asterisk's PJSIP Realtime engine **and**
    reachable by other extensions — all without editing config files or
    running ``dialplan reload``.

    All three PJSIP rows share the same ``id`` value (the username),
    which is the convention Asterisk expects: the endpoint's ``auth``
    and ``aors`` columns reference auth/AOR rows by their ``id``.

    ### NAT-traversal defaults

    The endpoint is created with ``rtp_symmetric=yes``,
    ``rewrite_contact=yes``, and ``force_rport=yes`` so that devices
    behind NAT (e.g. AudioCodes MP-114) work out of the box without
    one-way audio or registration issues.

    ### Auto-generated dialplan

    Two Realtime dialplan rows are inserted into the ``extensions``
    table so that dialling *username* from any extension in the same
    context will ring this endpoint::

        priority 1 → Dial(PJSIP/<username>,<ring_timeout>,tT)
        priority 2 → Hangup()
    """

    # --- Guard: prevent duplicate provisioning ----------------------------
    existing = session.exec(select(PsEndpoint).where(PsEndpoint.id == username)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Extension '{username}' already exists.",
        )

    # --- 1. Authentication row --------------------------------------------
    auth = PsAuth(
        id=username,
        auth_type="userpass",
        username=username,
        password=body.password,
    )

    # --- 2. AOR row -------------------------------------------------------
    # Defaults from the model/schema are fine for a small PBX:
    #   max_contacts=1     → one device per extension
    #   qualify_frequency=60 → OPTIONS ping every 60 s keeps NAT alive
    #   remove_existing=yes → newest registration always wins
    aor = PsAor(id=username)

    # --- 3. Endpoint row --------------------------------------------------
    # 'aors' and 'auth' reference the rows above by their id.
    # NAT-safe defaults are baked into the model, but we set them
    # explicitly here for clarity and auditability.
    endpoint = PsEndpoint(
        id=username,
        transport="transport-udp",
        aors=username,  # links to the ps_aors row
        auth=username,  # links to the ps_auths row
        context=body.context,  # dialplan context (default: from-internal)
        disallow="all",  # reset codec list …
        allow="ulaw,alaw",  # … then allow only G.711 (universal compat)
        direct_media="no",  # keep RTP anchored on Asterisk (NAT-safe)
        rtp_symmetric="yes",  # reply to observed source IP:port → fixes one-way audio
        force_rport="yes",  # honour rport even if device omits it (RFC 3581)
        rewrite_contact="yes",  # rewrite Contact with observed IP:port for in-dialog routing
        dtmf_mode="rfc4733",  # out-of-band DTMF via RTP events (most reliable)
    )

    # --- 4. Dialplan rows -------------------------------------------------
    # Insert Realtime dialplan entries so other extensions can dial this
    # one.  Asterisk picks these up instantly via pbx_realtime.
    session.add(auth)
    session.add(aor)
    session.add(endpoint)
    _create_dialplan_rows(session, username, body.context, body.ring_timeout)

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision '{username}': {exc}",
        ) from exc

    return {"status": "provisioned", "username": username}


# ---------------------------------------------------------------------------
# Deletion endpoint (convenience for re-provisioning during development)
# ---------------------------------------------------------------------------
@app.delete(
    "/provision/{username}",
    status_code=status.HTTP_200_OK,
    tags=["provisioning"],
    summary="Remove a provisioned SIP extension",
)
def deprovision_user(
    username: str,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """
    Remove all PJSIP Realtime rows **and** dialplan rows for *username*.

    Asterisk will stop recognising the extension on its next Realtime
    lookup (typically within seconds — no ``pjsip reload`` or
    ``dialplan reload`` needed).
    """

    endpoint = session.exec(select(PsEndpoint).where(PsEndpoint.id == username)).first()
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extension '{username}' not found.",
        )

    # Delete in reverse dependency order (endpoint → AOR → auth → dialplan).
    auth = session.exec(select(PsAuth).where(PsAuth.id == username)).first()
    aor = session.exec(select(PsAor).where(PsAor.id == username)).first()

    session.delete(endpoint)
    if aor is not None:
        session.delete(aor)
    if auth is not None:
        session.delete(auth)
    _delete_dialplan_rows(session, username)

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deprovision '{username}': {exc}",
        ) from exc

    return {"status": "deprovisioned", "username": username}
