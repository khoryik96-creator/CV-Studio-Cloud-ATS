BEGIN;
ALTER TABLE cvcloud.jobs
    DROP CONSTRAINT jobs_module_check,
    ADD CHECK (module IN ('cv_formatting', 'cv_blinding', 'cv_scoring', 'company_profile', 'blind_jd', 'create_profile')),
    ADD COLUMN profile_confirmation jsonb,
    ADD COLUMN profile_started_at timestamptz,
    ADD COLUMN profile_result jsonb,
    ADD CHECK (profile_confirmation IS NULL OR module = 'create_profile'),
    ADD CHECK (profile_started_at IS NULL OR profile_confirmation IS NOT NULL),
    ADD CHECK (profile_result IS NULL OR (profile_started_at IS NOT NULL AND state = 'succeeded'));

CREATE TABLE cvcloud.jobadder_fixture_config (
    tenant_id uuid PRIMARY KEY REFERENCES cvcloud.tenants(id),
    account_id uuid NOT NULL UNIQUE,
    credential_digest char(64) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
);
CREATE TABLE cvcloud.jobadder_fixture_candidates (
    tenant_id uuid NOT NULL REFERENCES cvcloud.jobadder_fixture_config(tenant_id),
    id uuid NOT NULL,
    email text NOT NULL,
    candidate_name text NOT NULL,
    cv bytea NOT NULL,
    mime text NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, email)
);
CREATE TABLE cvcloud.jobadder_fixture_operations (
    tenant_id uuid NOT NULL REFERENCES cvcloud.jobadder_fixture_config(tenant_id),
    owner_id uuid NOT NULL,
    job_id uuid NOT NULL,
    candidate_id uuid,
    duplicate boolean NOT NULL,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id, owner_id) REFERENCES cvcloud.jobs(tenant_id, id, owner_id),
    FOREIGN KEY (tenant_id, candidate_id) REFERENCES cvcloud.jobadder_fixture_candidates(tenant_id, id),
    CHECK (duplicate = (candidate_id IS NULL))
);

ALTER TABLE cvcloud.jobadder_fixture_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobadder_fixture_config FORCE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobadder_fixture_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobadder_fixture_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobadder_fixture_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobadder_fixture_operations FORCE ROW LEVEL SECURITY;

CREATE POLICY fixture_config_read ON cvcloud.jobadder_fixture_config FOR SELECT
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true));
CREATE POLICY fixture_candidate_access ON cvcloud.jobadder_fixture_candidates FOR ALL
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true));
CREATE POLICY fixture_operation_access ON cvcloud.jobadder_fixture_operations FOR ALL
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true) AND owner_id::text=current_setting('cvcloud.user_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true) AND owner_id::text=current_setting('cvcloud.user_id',true));
COMMIT;
