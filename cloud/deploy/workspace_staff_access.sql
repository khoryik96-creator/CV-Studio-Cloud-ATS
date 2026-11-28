-- Additive staff enrollment policy, separate from password recovery.
BEGIN;
CREATE TABLE cvcloud.staff_enrollments (
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest text NOT NULL UNIQUE CHECK (token_digest ~ '^[a-f0-9]{64}$'),
    credential_version bigint NOT NULL,
    tenant_epoch bigint NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id,user_id),
    FOREIGN KEY (tenant_id,user_id) REFERENCES cvcloud.users(tenant_id,id) ON DELETE CASCADE
);
CREATE FUNCTION cvcloud.redeem_staff_enrollment(p_digest text,p_session text,p_csrf text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid; u uuid; epoch bigint; version bigint; staff_account_role text; challenge record;
BEGIN
    IF p_digest IS NULL OR p_session IS NULL OR p_csrf IS NULL
       OR p_digest !~ '^[a-f0-9]{64}$' OR p_session !~ '^[a-f0-9]{64}$'
       OR p_csrf !~ '^[A-Za-z0-9_-]{43}$' THEN RETURN false; END IF;
    SELECT e.tenant_id,e.user_id INTO t,u FROM cvcloud.staff_enrollments e
        WHERE e.token_digest=p_digest AND e.expires_at>clock_timestamp();
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT auth_epoch INTO epoch FROM cvcloud.tenants WHERE id=t AND active FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT credential_version,role INTO version,staff_account_role FROM cvcloud.users
        WHERE tenant_id=t AND id=u AND active FOR UPDATE;
    IF NOT FOUND OR staff_account_role<>'recruiter' THEN RETURN false; END IF;
    SELECT * INTO challenge FROM cvcloud.staff_enrollments e
        WHERE e.tenant_id=t AND e.user_id=u AND e.token_digest=p_digest FOR UPDATE;
    IF NOT FOUND OR challenge.expires_at<=clock_timestamp()
       OR challenge.credential_version<>version OR challenge.tenant_epoch<>epoch THEN RETURN false; END IF;
    INSERT INTO cvcloud.sessions (token_digest,csrf_token,tenant_id,user_id,expires_at,credential_version,tenant_epoch)
        VALUES(p_session,p_csrf,t,u,clock_timestamp()+interval '90 days',version,epoch);
    DELETE FROM cvcloud.staff_enrollments WHERE tenant_id=t AND user_id=u;
    RETURN true;
END;
$body$;
REVOKE ALL ON FUNCTION cvcloud.redeem_staff_enrollment(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cvcloud.redeem_staff_enrollment(text,text,text) TO cvcloud_auth;
COMMIT;
