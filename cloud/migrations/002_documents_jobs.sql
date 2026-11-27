-- Dedicated cloud database only. Migration role must differ from runtime role.
BEGIN;
CREATE TABLE cvcloud.documents (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    media_type text NOT NULL CHECK (media_type IN ('application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain')),
    byte_size bigint NOT NULL CHECK (byte_size BETWEEN 1 AND 33554432),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,id,owner_id),
    FOREIGN KEY (tenant_id,owner_id) REFERENCES cvcloud.users(tenant_id,id)
);
CREATE TABLE cvcloud.jobs (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    document_id uuid NOT NULL,
    module text NOT NULL CHECK (module IN ('cv_formatting','cv_blinding','cv_scoring','company_profile','blind_jd')),
    idempotency_key uuid NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','succeeded','failed','needs_review')),
    lease_token uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,owner_id,idempotency_key),
    FOREIGN KEY (tenant_id,document_id,owner_id) REFERENCES cvcloud.documents(tenant_id,id,owner_id),
    CHECK ((state='running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
        OR (state<>'running' AND lease_token IS NULL AND lease_until IS NULL))
);
CREATE INDEX ON cvcloud.jobs (tenant_id,state,created_at,id);
CREATE INDEX ON cvcloud.jobs (tenant_id,lease_until) WHERE state='running';
-- Default deny when settings are absent. Runtime role must not own tables or have BYPASSRLS.
ALTER TABLE cvcloud.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.documents FORCE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY document_owner ON cvcloud.documents
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
       AND owner_id::text=current_setting('cvcloud.user_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
       AND owner_id::text=current_setting('cvcloud.user_id',true));
CREATE POLICY job_owner ON cvcloud.jobs
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
       AND owner_id::text=current_setting('cvcloud.user_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
       AND owner_id::text=current_setting('cvcloud.user_id',true));
COMMIT;
