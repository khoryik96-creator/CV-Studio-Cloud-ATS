-- Additive sandbox attempt journal; no runtime direct table access.
BEGIN;
CREATE TABLE cvcloud.crm_attempts (
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    job_id uuid NOT NULL,
    account_id text NOT NULL CHECK (account_id ~ '^[A-Za-z0-9_-]{1,128}$'),
    email_digest text NOT NULL CHECK (email_digest ~ '^[a-f0-9]{64}$'),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,job_id),
    UNIQUE (tenant_id,account_id,email_digest),
    FOREIGN KEY (tenant_id,job_id,owner_id) REFERENCES cvcloud.jobs(tenant_id,id,owner_id)
);
ALTER TABLE cvcloud.crm_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.crm_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY crm_attempt_scope ON cvcloud.crm_attempts FOR INSERT
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND owner_id::text=current_setting('cvcloud.user_id',true));
CREATE FUNCTION cvcloud.record_crm_attempt(p_job uuid,p_lease uuid,p_account text,p_digest text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE t uuid; u uuid; recorded uuid;
BEGIN
    t:=nullif(current_setting('cvcloud.tenant_id',true),'')::uuid;
    u:=nullif(current_setting('cvcloud.user_id',true),'')::uuid;
    IF t IS NULL OR u IS NULL OR p_job IS NULL OR p_lease IS NULL
       OR p_account IS NULL OR p_digest IS NULL OR cvcloud.lock_workspace_account(false) IS NULL THEN
        RETURN false;
    END IF;
    PERFORM 1 FROM cvcloud.jobs j
        WHERE j.tenant_id=t AND j.owner_id=u AND j.id=p_job AND j.module='create_profile'
          AND j.state='running' AND j.lease_token=p_lease AND j.lease_until>clock_timestamp()
          AND j.profile_started_at IS NOT NULL
          AND j.profile_confirmation->'settings'->>'account_id'=p_account
          AND j.profile_confirmation->'settings'->>'environment'='sandbox'
        FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    INSERT INTO cvcloud.crm_attempts (tenant_id,owner_id,job_id,account_id,email_digest)
        VALUES(t,u,p_job,p_account,p_digest) ON CONFLICT DO NOTHING;
    RETURN FOUND;
END;
$body$;
REVOKE ALL ON FUNCTION cvcloud.record_crm_attempt(uuid,uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cvcloud.record_crm_attempt(uuid,uuid,text,text) TO cvcloud_worker;
GRANT UPDATE (profile_confirmation) ON cvcloud.jobs TO cvcloud_document;
GRANT UPDATE (profile_started_at,profile_result) ON cvcloud.jobs TO cvcloud_worker;
COMMIT;
