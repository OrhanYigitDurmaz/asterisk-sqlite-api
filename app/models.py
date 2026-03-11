"""
SQLModel ORM models for Asterisk 20 PJSIP Realtime tables.

Each class maps 1:1 to the table names and columns defined in schema.sql.
Asterisk's Realtime engine queries these tables by exact name (ps_auths,
ps_aors, ps_endpoints), so __tablename__ must match precisely.
"""

from typing import Optional

from sqlmodel import Field, SQLModel


class PsAuth(SQLModel, table=True):
    """
    PJSIP authentication credentials.

    Asterisk looks up this table when a REGISTER or INVITE arrives and
    the endpoint's 'auth' column points here.  We default to 'userpass'
    (plain-text) auth_type because it is the simplest for small PBXes;
    for production hardening, consider 'md5' with md5_cred instead.
    """

    __tablename__ = "ps_auths"  # type: ignore[assignment]

    id: str = Field(max_length=40, primary_key=True)
    auth_type: str = Field(default="userpass", max_length=40)
    username: Optional[str] = Field(default=None, max_length=80)
    password: Optional[str] = Field(default=None, max_length=80)
    nonce_lifetime: Optional[int] = Field(default=None)
    md5_cred: Optional[str] = Field(default=None, max_length=40)
    realm: Optional[str] = Field(default=None, max_length=40)


class PsAor(SQLModel, table=True):
    """
    PJSIP Address-of-Record (registration binding).

    Controls how many devices can register under one extension, how often
    Asterisk sends OPTIONS qualify pings, and registration expiry windows.

    - max_contacts=1: only one device per extension (avoids fork-bombing
      on a 6-user PBX).
    - remove_existing='yes': if a second device registers, kick the old
      binding so the newest device always wins.
    - qualify_frequency=60: send OPTIONS every 60 s to detect dead endpoints
      quickly and keep NAT pinholes open.
    """

    __tablename__ = "ps_aors"  # type: ignore[assignment]

    id: str = Field(max_length=40, primary_key=True)
    max_contacts: int = Field(default=1)
    remove_existing: str = Field(default="yes", max_length=10)
    minimum_expiration: int = Field(default=60)
    default_expiration: int = Field(default=3600)
    maximum_expiration: int = Field(default=7200)
    qualify_frequency: int = Field(default=60)
    authenticate_qualify: str = Field(default="no", max_length=10)


class PsEndpoint(SQLModel, table=True):
    """
    PJSIP endpoint definition — the central object that ties auth + AOR
    together and controls media behaviour.

    NAT-traversal settings (critical for AudioCodes MP-114 and similar
    gateways sitting behind consumer routers):

    - rtp_symmetric='yes':   Send RTP back to the source IP:port we
                              *received* from, not the one in the SDP.
                              Fixes one-way audio behind NAT.
    - force_rport='yes':     Honour rport (RFC 3581) even if the device
                              doesn't request it, so responses go to the
                              observed source port.
    - rewrite_contact='yes': Rewrite the Contact header with the observed
                              IP:port so subsequent in-dialog requests
                              (re-INVITEs, BYEs) reach the device.
    - direct_media='no':     Force all RTP through Asterisk (no reinvite).
                              Essential when both legs are behind NAT.
    - dtmf_mode='rfc4733':   Out-of-band DTMF via RTP event packets —
                              the most reliable method for SIP trunks and
                              ATAs like the MP-114.
    """

    __tablename__ = "ps_endpoints"  # type: ignore[assignment]

    id: str = Field(max_length=40, primary_key=True)
    transport: str = Field(default="transport-udp", max_length=40)
    aors: Optional[str] = Field(default=None, max_length=200)
    auth: Optional[str] = Field(default=None, max_length=200)
    context: str = Field(default="from-internal", max_length=40)
    disallow: str = Field(default="all", max_length=200)
    allow: str = Field(default="ulaw,alaw", max_length=200)
    direct_media: str = Field(default="no", max_length=10)
    # -- NAT traversal knobs (see class docstring) --
    rtp_symmetric: str = Field(default="yes", max_length=10)
    force_rport: str = Field(default="yes", max_length=10)
    rewrite_contact: str = Field(default="yes", max_length=10)
    dtmf_mode: str = Field(default="rfc4733", max_length=20)


class ProvisionRequest(SQLModel):
    """
    Pydantic request body for the POST /provision/{username} endpoint.

    Not a database table — just a validation schema for the incoming JSON.
    """

    password: str = Field(min_length=8, max_length=80)
    context: str = Field(default="from-internal", max_length=40)
