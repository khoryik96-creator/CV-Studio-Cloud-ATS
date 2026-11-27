-- Private immutable outputs, independent of input documents.
BEGIN;
CREATE TABLE cvcloud.job_outputs (
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    job_id uuid NOT NULL,
    object_id uuid NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size BETWEEN 1 AND 33554432),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    requires_review boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,job_id),
    UNIQUE (tenant_id,object_id),
    FOREIGN KEY (tenant_id,job_id,owner_id) REFERENCES cvcloud.jobs(tenant_id,id,owner_id)
);
ALTER TABLE cvcloud.job_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.job_outputs FORCE ROW LEVEL SECURITY;
CREATE POLICY output_owner ON cvcloud.job_outputs
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND owner_id::text=current_setting('cvcloud.user_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND owner_id::text=current_setting('cvcloud.user_id',true));
COMMIT;
