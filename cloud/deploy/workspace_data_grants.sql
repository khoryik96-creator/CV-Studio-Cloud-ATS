-- Apply only as the dedicated schema owner after workspace migrations.
-- Roles are provisioned separately; this script never resets credentials.
BEGIN;
DO $guard$
BEGIN
    IF current_database() <> 'cvcloud_online' OR current_user <> 'cvcloud_schema_owner'
       OR to_regclass('cvcloud.online_workspace_migrations') IS NULL THEN
        RAISE EXCEPTION 'Dedicated marked workspace required';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN
        ('cvcloud_document','cvcloud_worker','cvcloud_provider','cvcloud_provider_reader','cvcloud_scheduler')
        AND rolcanlogin AND NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit)) <> 5
       OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
         WHERE r.rolname IN ('cvcloud_document','cvcloud_worker','cvcloud_provider','cvcloud_provider_reader','cvcloud_scheduler')) THEN
        RAISE EXCEPTION 'Restricted standalone workspace roles required';
    END IF;
END;
$guard$;
-- Acquire row locks as the schema owner, without giving callers UPDATE rights.
-- Scope comes from the trusted transaction-local principal. No password hash,
-- email, session or other account data is exposed by the function.
CREATE FUNCTION cvcloud.lock_workspace_account(p_exclusive boolean)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $lock$
DECLARE t uuid; u uuid; answer text;
BEGIN
    t := nullif(current_setting('cvcloud.tenant_id',true),'')::uuid;
    u := nullif(current_setting('cvcloud.user_id',true),'')::uuid;
    IF t IS NULL OR u IS NULL THEN RETURN NULL; END IF;
    PERFORM 1 FROM cvcloud.tenants WHERE id=t AND active FOR SHARE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF p_exclusive IS TRUE THEN
        SELECT role INTO answer FROM cvcloud.users WHERE tenant_id=t AND id=u AND active FOR UPDATE;
    ELSE
        SELECT role INTO answer FROM cvcloud.users WHERE tenant_id=t AND id=u AND active FOR SHARE;
    END IF;
    RETURN answer;
END;
$lock$;
REVOKE ALL ON FUNCTION cvcloud.lock_workspace_account(boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cvcloud.lock_workspace_account(boolean)
    TO cvcloud_document,cvcloud_worker,cvcloud_provider,cvcloud_provider_reader;
GRANT USAGE ON SCHEMA cvcloud TO cvcloud_document,cvcloud_worker,cvcloud_provider,cvcloud_provider_reader,cvcloud_scheduler;
-- Only metadata necessary for active-account joins and provider RLS policies.
GRANT SELECT (tenant_id,id,active,role) ON cvcloud.users TO cvcloud_document,cvcloud_worker,cvcloud_provider,cvcloud_provider_reader;
GRANT SELECT (id,active) ON cvcloud.tenants TO cvcloud_document,cvcloud_worker,cvcloud_provider,cvcloud_provider_reader;
-- Admission cannot set job result, lease or state columns.
GRANT SELECT ON cvcloud.documents,cvcloud.jobs,cvcloud.job_outputs TO cvcloud_document;
GRANT INSERT (tenant_id,id,owner_id,media_type,byte_size,sha256) ON cvcloud.documents TO cvcloud_document;
GRANT INSERT (tenant_id,id,owner_id,document_id,module,idempotency_key,alignment,correct_language,neutral_gender) ON cvcloud.jobs TO cvcloud_document;
GRANT UPDATE (scoring_jd_id,scoring_criteria) ON cvcloud.jobs TO cvcloud_document;
-- Worker cannot create input documents or change admission options/budget cap.
GRANT SELECT ON cvcloud.documents,cvcloud.jobs,cvcloud.job_outputs,cvcloud.ai_budgets,cvcloud.ai_reservations TO cvcloud_worker;
GRANT UPDATE (state,lease_token,lease_until,updated_at,scoring_result) ON cvcloud.jobs TO cvcloud_worker;
GRANT INSERT (tenant_id,owner_id,job_id,object_id,byte_size,sha256,requires_review) ON cvcloud.job_outputs TO cvcloud_worker;
GRANT UPDATE (reserved_microusd,spent_microusd) ON cvcloud.ai_budgets TO cvcloud_worker;
GRANT INSERT (tenant_id,owner_id,job_id,operation_id,lease_token,provider,model,reserved_microusd) ON cvcloud.ai_reservations TO cvcloud_worker;
GRANT UPDATE (actual_microusd,settled_at) ON cvcloud.ai_reservations TO cvcloud_worker;
-- Web can store encrypted credentials but cannot read their ciphertext.
GRANT SELECT (tenant_id,revision,provider,model,enabled) ON cvcloud.provider_config TO cvcloud_provider;
GRANT INSERT (tenant_id,revision,provider,model,enabled,key_version,nonce,ciphertext,updated_by) ON cvcloud.provider_config TO cvcloud_provider;
GRANT UPDATE (revision,provider,model,enabled,key_version,nonce,ciphertext,updated_by,updated_at) ON cvcloud.provider_config TO cvcloud_provider;
-- Worker can read credential envelope, but cannot configure or rotate it.
GRANT SELECT ON cvcloud.provider_config TO cvcloud_provider_reader;
GRANT EXECUTE ON FUNCTION cvcloud.active_worker_roster() TO cvcloud_scheduler;
-- No account administration grants, real research or CRM grants in this batch.
COMMIT;
