"""
FastAPI provisioning API for Asterisk 20 PJSIP Realtime (SQLite backend).

This micro-service exposes a single endpoint that atomically creates
the three PJSIP Realtime rows (auth, AOR, endpoint) required for a
SIP extension to become immediately usable by Asterisk without a reload.

Designed for a minimalist 6-user PBX running on Alpine Linux in Docker.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session, init_db
from app.models import ProvisionRequest, PsAor, PsAuth, PsEndpoint


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
    version="1.0.0",
    description="Provision SIP extensions into Asterisk 20 Realtime (SQLite).",
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
    Atomically create **ps_auths**, **ps_aors**, and **ps_endpoints** rows
    for *username* so the extension is immediately available to Asterisk's
    PJSIP Realtime engine.

    All three rows share the same ``id`` value (the username), which is the
    convention Asterisk expects: the endpoint's ``auth`` and ``aors``
    columns reference auth/AOR rows by their ``id``.

    ### NAT-traversal defaults

    The endpoint is created with ``rtp_symmetric=yes``,
    ``rewrite_contact=yes``, and ``force_rport=yes`` so that devices
    behind NAT (e.g. AudioCodes MP-114) work out of the box without
    one-way audio or registration issues.
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

    # --- Atomic insert: all three rows in a single transaction ------------
    session.add(auth)
    session.add(aor)
    session.add(endpoint)

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
    Remove all three Realtime rows for *username*.

    Asterisk will stop recognising the extension on its next Realtime
    lookup (typically within seconds — no ``pjsip reload`` needed).
    """

    endpoint = session.exec(select(PsEndpoint).where(PsEndpoint.id == username)).first()
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extension '{username}' not found.",
        )

    # Delete in reverse dependency order (endpoint → AOR → auth).
    auth = session.exec(select(PsAuth).where(PsAuth.id == username)).first()
    aor = session.exec(select(PsAor).where(PsAor.id == username)).first()

    session.delete(endpoint)
    if aor is not None:
        session.delete(aor)
    if auth is not None:
        session.delete(auth)

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deprovision '{username}': {exc}",
        ) from exc

    return {"status": "deprovisioned", "username": username}
