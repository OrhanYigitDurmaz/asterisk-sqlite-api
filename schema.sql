CREATE TABLE IF NOT EXISTS ps_auths (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    auth_type VARCHAR(40) DEFAULT 'userpass',
    username VARCHAR(80),
    password VARCHAR(80),
    nonce_lifetime INTEGER,
    md5_cred VARCHAR(40),
    realm VARCHAR(40)
);

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

CREATE TABLE IF NOT EXISTS ps_endpoints (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    transport VARCHAR(40) DEFAULT 'transport-ws',
    aors VARCHAR(200),
    auth VARCHAR(200),
    context VARCHAR(40) DEFAULT 'from-internal',
    disallow VARCHAR(200) DEFAULT 'all',
    allow VARCHAR(200) DEFAULT 'ulaw,alaw,opus',
    webrtc VARCHAR(10) DEFAULT 'yes',
    dtmf_mode VARCHAR(20) DEFAULT 'rfc4733',
    rtp_symmetric VARCHAR(10) DEFAULT 'yes',
    force_rport VARCHAR(10) DEFAULT 'yes',
    rewrite_contact VARCHAR(10) DEFAULT 'yes',
    direct_media VARCHAR(10) DEFAULT 'no',
    callerid VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context VARCHAR(40) NOT NULL,
    exten VARCHAR(40) NOT NULL,
    priority INTEGER NOT NULL,
    app VARCHAR(40) NOT NULL,
    appdata VARCHAR(256) NOT NULL,
    UNIQUE(context, exten, priority)
);

CREATE INDEX IF NOT EXISTS idx_extensions_context_exten
    ON extensions (context, exten);
