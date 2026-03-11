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
