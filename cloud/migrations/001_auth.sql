-- Apply explicitly to a dedicated CV Studio Cloud database; not HyPlug.
BEGIN;
CREATE SCHEMA cvcloud;
CREATE TABLE cvcloud.tenants (
    id uuid PRIMARY KEY,
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE cvcloud.users (
    tenant_id uuid NOT NULL REFERENCES cvcloud.tenants(id),
    id uuid NOT NULL,
    email_normalized text NOT NULL CHECK (length(email_normalized) BETWEEN 3 AND 254),
    password_hash text NOT NULL,
    credential_version bigint NOT NULL DEFAULT 1 CHECK (credential_version > 0),
    role text NOT NULL CHECK (role IN ('owner','admin','recruiter')),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,email_normalized)
);
CREATE TABLE cvcloud.sessions (
    token_digest char(64) PRIMARY KEY CHECK (token_digest ~ '^[a-f0-9]{64}$'),
    csrf_token text NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    credential_version bigint NOT NULL,
    FOREIGN KEY (tenant_id,user_id) REFERENCES cvcloud.users(tenant_id,id) ON DELETE CASCADE
);
CREATE FUNCTION cvcloud.bump_credential_version() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog AS $
BEGIN
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash OR NEW.active IS DISTINCT FROM OLD.active THEN
        NEW.credential_version := OLD.credential_version + 1;
    END IF;
    RETURN NEW;
END;
$;
CREATE TRIGGER user_credential_change BEFORE UPDATE ON cvcloud.users
FOR EACH ROW EXECUTE FUNCTION cvcloud.bump_credential_version();
-- Tenant disable/enable must invalidate existing sessions as well.
CREATE FUNCTION cvcloud.revoke_tenant_sessions() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog AS $
BEGIN
    IF NEW.active IS DISTINCT FROM OLD.active THEN
        DELETE FROM cvcloud.sessions WHERE tenant_id=NEW.id;
    END IF;
    RETURN NEW;
END;
$;
CREATE TRIGGER tenant_status_change AFTER UPDATE OF active ON cvcloud.tenants
FOR EACH ROW EXECUTE FUNCTION cvcloud.revoke_tenant_sessions();
CREATE INDEX ON cvcloud.sessions (expires_at);
CREATE INDEX ON cvcloud.sessions (tenant_id,user_id);
CREATE TABLE cvcloud.login_attempts (
    bucket char(64) NOT NULL,
    window_start timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts BETWEEN 1 AND 11),
    PRIMARY KEY (bucket,window_start)
);
COMMIT;
