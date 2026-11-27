BEGIN;
-- Like sessions, this table is accessed by trusted authentication services,
-- never by end-user SQL. Production grants must isolate token lookup/consume
-- from document workers. Only a SHA-256 digest is persisted.
CREATE TABLE cvcloud.account_challenges (
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest char(64) NOT NULL UNIQUE CHECK (token_digest ~ '^[a-f0-9]{64}$'),
    purpose text NOT NULL CHECK (purpose IN ('invite','reset')),
    credential_version bigint NOT NULL CHECK (credential_version>0),
    tenant_epoch bigint NOT NULL CHECK (tenant_epoch>0),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id,user_id),
    FOREIGN KEY (tenant_id,user_id) REFERENCES cvcloud.users(tenant_id,id)
);
CREATE INDEX ON cvcloud.account_challenges (expires_at);
COMMIT;
