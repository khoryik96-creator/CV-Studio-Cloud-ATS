BEGIN;
CREATE INDEX ON cvcloud.jobs (tenant_id,owner_id,created_at DESC,id DESC);
CREATE INDEX ON cvcloud.documents (tenant_id,owner_id,created_at DESC,id DESC);
CREATE INDEX ON cvcloud.jobs (tenant_id,owner_id,document_id);
COMMIT;
