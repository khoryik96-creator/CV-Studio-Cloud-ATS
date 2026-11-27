-- Prevent credentials checked before a disable/enable cycle from issuing a new session.
BEGIN;
ALTER TABLE cvcloud.tenants ADD COLUMN auth_epoch bigint NOT NULL DEFAULT 1 CHECK (auth_epoch>0);
ALTER TABLE cvcloud.sessions ADD COLUMN tenant_epoch bigint NOT NULL DEFAULT 1 CHECK (tenant_epoch>0);
CREATE FUNCTION cvcloud.bump_tenant_epoch() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog AS $epoch$
BEGIN
    IF NEW.active IS DISTINCT FROM OLD.active THEN
        NEW.auth_epoch := OLD.auth_epoch + 1;
    END IF;
    RETURN NEW;
END;
$epoch$;
CREATE TRIGGER tenant_auth_epoch BEFORE UPDATE OF active ON cvcloud.tenants
FOR EACH ROW EXECUTE FUNCTION cvcloud.bump_tenant_epoch();
COMMIT;
