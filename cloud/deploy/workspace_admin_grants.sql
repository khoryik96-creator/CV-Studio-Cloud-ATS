-- Separate account-administration boundary. Install only after reviewed
-- workspace migration/grants. No direct account or session table grants.
BEGIN;
DO $guard$
BEGIN
    IF current_database() <> 'cvcloud_online' OR current_user <> 'cvcloud_schema_owner'
        OR to_regclass('cvcloud.online_workspace_grants') IS NULL
        OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cvcloud_admin'
            AND rolcanlogin AND NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit))
        OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='cvcloud_admin') THEN
        RAISE EXCEPTION 'Dedicated workspace and restricted admin role required';
    END IF;
END;
$guard$;
-- The role uses transaction-local, server-derived identity. Like other
-- backend roles, its credentials must never be exposed to end users.
CREATE FUNCTION cvcloud.admin_actor_lock()
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid; a uuid; actor_role text;
BEGIN
    t := nullif(current_setting('cvcloud.tenant_id',true),'')::uuid;
    a := nullif(current_setting('cvcloud.user_id',true),'')::uuid;
    IF t IS NULL OR a IS NULL THEN RETURN NULL; END IF;
    PERFORM 1 FROM cvcloud.tenants WHERE id=t AND active FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT u.role INTO actor_role FROM cvcloud.users u
        WHERE u.tenant_id=t AND u.id=a AND u.active FOR SHARE;
    IF actor_role IS NULL OR actor_role NOT IN ('owner','admin') THEN RETURN NULL; END IF;
    RETURN actor_role;
END;
$body$;
REVOKE ALL ON FUNCTION cvcloud.admin_actor_lock() FROM PUBLIC;

CREATE FUNCTION cvcloud.admin_list_accounts()
RETURNS TABLE(user_id text,email text,role text,active boolean,revision bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid; a uuid; actor_role text;
BEGIN
    actor_role := cvcloud.admin_actor_lock();
    IF actor_role IS NULL THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied'; END IF;
    t := current_setting('cvcloud.tenant_id')::uuid;
    a := current_setting('cvcloud.user_id')::uuid;
    IF (SELECT count(*) FROM (SELECT 1 FROM cvcloud.users u WHERE u.tenant_id=t LIMIT 101) AS bounded)>100 THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_limit_exceeded';
    END IF;
    RETURN QUERY SELECT u.id::text,u.email_normalized,u.role,u.active,u.credential_version
        FROM cvcloud.users u WHERE u.tenant_id=t AND
        (u.id=a OR u.role='recruiter' OR (actor_role='owner' AND u.role='admin'))
        ORDER BY u.email_normalized,u.id;
END;
$body$;

CREATE FUNCTION cvcloud.admin_change_account(p_target uuid,p_revision bigint,p_action text,p_value text,p_event uuid)
RETURNS TABLE(user_id text,email text,role text,active boolean,revision bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid; a uuid; actor_role text; old_role text; old_active boolean; old_revision bigint;
BEGIN
    actor_role := cvcloud.admin_actor_lock();
    IF actor_role IS NULL THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied'; END IF;
    t := current_setting('cvcloud.tenant_id')::uuid;
    a := current_setting('cvcloud.user_id')::uuid;
    IF p_target IS NULL OR p_target=a THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied'; END IF;
    IF p_event IS NULL OR p_revision IS NULL OR p_revision<1 OR p_revision>=9223372036854775807
        OR p_action IS NULL OR p_action NOT IN ('role_change','suspend','reactivate','revoke_sessions') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='invalid_action';
    END IF;
    SELECT u.role,u.active,u.credential_version INTO old_role,old_active,old_revision
        FROM cvcloud.users u WHERE u.tenant_id=t AND u.id=p_target FOR UPDATE;
    IF NOT FOUND OR NOT (old_role='recruiter' OR (actor_role='owner' AND old_role='admin')) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied';
    END IF;
    IF old_revision<>p_revision THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_conflict'; END IF;
    IF EXISTS (SELECT 1 FROM cvcloud.account_challenges c WHERE c.tenant_id=t AND c.user_id=p_target AND c.purpose='invite') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied';
    END IF;
    IF p_action='role_change' THEN
        IF p_value IS NULL OR p_value=old_role OR NOT (p_value='recruiter' OR (actor_role='owner' AND p_value='admin')) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='invalid_role_change';
        END IF;
        UPDATE cvcloud.users u SET role=p_value WHERE u.tenant_id=t AND u.id=p_target;
    ELSE
        IF p_value IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='invalid_action'; END IF;
        IF p_action='revoke_sessions' THEN
            UPDATE cvcloud.users u SET credential_version=u.credential_version+1 WHERE u.tenant_id=t AND u.id=p_target;
        ELSE
            IF old_active=(p_action='reactivate') THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='invalid_state_change'; END IF;
            UPDATE cvcloud.users u SET active=(p_action='reactivate') WHERE u.tenant_id=t AND u.id=p_target;
        END IF;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cvcloud.users u WHERE u.tenant_id=t AND u.id=p_target AND u.credential_version=p_revision+1) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_conflict';
    END IF;
    DELETE FROM cvcloud.sessions s WHERE s.tenant_id=t AND s.user_id=p_target;
    INSERT INTO cvcloud.account_audit (tenant_id,event_id,actor_id,target_id,action)
        VALUES(t,p_event,a,p_target,p_action);
    RETURN QUERY SELECT u.id::text,u.email_normalized,u.role,u.active,u.credential_version
        FROM cvcloud.users u WHERE u.tenant_id=t AND u.id=p_target;
END;
$body$;

CREATE FUNCTION cvcloud.admin_usage_snapshot()
RETURNS TABLE(limit_microusd bigint,reserved_microusd bigint,spent_microusd bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid;
BEGIN
    IF cvcloud.admin_actor_lock() IS NULL THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='account_admin_denied'; END IF;
    t := current_setting('cvcloud.tenant_id')::uuid;
    RETURN QUERY SELECT b.limit_microusd,b.reserved_microusd,b.spent_microusd
        FROM cvcloud.ai_budgets b WHERE b.tenant_id=t;
END;
$body$;
REVOKE ALL ON FUNCTION cvcloud.admin_list_accounts(),cvcloud.admin_change_account(uuid,bigint,text,text,uuid),cvcloud.admin_usage_snapshot() FROM PUBLIC;
GRANT USAGE ON SCHEMA cvcloud TO cvcloud_admin;
GRANT EXECUTE ON FUNCTION cvcloud.admin_list_accounts(),cvcloud.admin_change_account(uuid,bigint,text,text,uuid),cvcloud.admin_usage_snapshot() TO cvcloud_admin;
COMMIT;
