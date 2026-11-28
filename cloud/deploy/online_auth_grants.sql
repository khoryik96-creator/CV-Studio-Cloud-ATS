-- Explicit, dedicated cvcloud_online database only; apply as schema owner.
-- Apply 001_auth.sql and 004_auth_epoch.sql first. Create cvcloud_auth as a
-- restricted LOGIN role with a generated password separately.
BEGIN;
DO $guard$
BEGIN
    IF current_database() <> 'cvcloud_online' THEN
        RAISE EXCEPTION 'Wrong database for online authentication grants';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cvcloud_auth'
        AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)) THEN
        RAISE EXCEPTION 'Unsafe authentication role';
    END IF;
    IF current_user = 'cvcloud_auth' OR EXISTS (
        SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='cvcloud_auth')
    ) THEN
        RAISE EXCEPTION 'Authentication role must not own schema or inherit roles';
    END IF;
END;
$guard$;
REVOKE ALL ON SCHEMA cvcloud FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cvcloud FROM PUBLIC;
GRANT USAGE ON SCHEMA cvcloud TO cvcloud_auth;
GRANT SELECT ON cvcloud.users,cvcloud.tenants TO cvcloud_auth;
GRANT SELECT,INSERT,DELETE ON cvcloud.sessions TO cvcloud_auth;
GRANT SELECT,INSERT,UPDATE,DELETE ON cvcloud.login_attempts TO cvcloud_auth;
-- Row locks ordinarily require UPDATE rights. Grant a narrow lock function
-- instead of allowing the auth role to modify tenant/account credentials.
CREATE FUNCTION cvcloud.lock_auth_account(p_tenant uuid,p_user uuid,p_hash text,
        p_version bigint,p_epoch bigint)
RETURNS TABLE(credential_version bigint,tenant_epoch bigint)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $lock$
    SELECT u.credential_version,t.auth_epoch
    FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
    WHERE u.tenant_id=p_tenant AND u.id=p_user AND u.password_hash=p_hash
      AND u.credential_version=p_version AND t.auth_epoch=p_epoch
      AND u.active AND t.active
    FOR SHARE OF u,t
$lock$;
REVOKE ALL ON FUNCTION cvcloud.lock_auth_account(uuid,uuid,text,bigint,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cvcloud.lock_auth_account(uuid,uuid,text,bigint,bigint) TO cvcloud_auth;
COMMIT;
