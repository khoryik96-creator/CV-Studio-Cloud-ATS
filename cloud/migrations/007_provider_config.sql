BEGIN;
-- One selected provider per tenant for the initial CV worker runtime.
-- Disabled rows keep the revision but never retain the encrypted credential.
CREATE TABLE cvcloud.provider_config (
    tenant_id uuid PRIMARY KEY REFERENCES cvcloud.tenants(id),
    revision bigint NOT NULL CHECK (revision > 0),
    provider text NOT NULL CHECK (provider = 'deepseek'),
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
    enabled boolean NOT NULL,
    key_version text,
    nonce bytea,
    ciphertext bytea,
    updated_by uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id,updated_by) REFERENCES cvcloud.users(tenant_id,id),
    CHECK ((enabled AND key_version IS NOT NULL AND key_version ~ '^[a-zA-Z0-9_-]{1,32}$'
        AND nonce IS NOT NULL AND octet_length(nonce)=12 AND ciphertext IS NOT NULL
        AND octet_length(ciphertext) BETWEEN 17 AND 4112)
        OR (NOT enabled AND key_version IS NULL AND nonce IS NULL AND ciphertext IS NULL))
);
ALTER TABLE cvcloud.provider_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.provider_config FORCE ROW LEVEL SECURITY;
CREATE POLICY provider_config_read ON cvcloud.provider_config FOR SELECT
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.tenant_id=provider_config.tenant_id AND u.id::text=current_setting('cvcloud.user_id',true)
            AND u.active AND t.active));
CREATE POLICY provider_config_insert ON cvcloud.provider_config FOR INSERT
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND updated_by::text=current_setting('cvcloud.user_id',true)
        AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.tenant_id=provider_config.tenant_id AND u.id::text=current_setting('cvcloud.user_id',true)
            AND u.active AND t.active AND u.role IN ('owner','admin')));
CREATE POLICY provider_config_update ON cvcloud.provider_config FOR UPDATE
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.tenant_id=provider_config.tenant_id AND u.id::text=current_setting('cvcloud.user_id',true)
            AND u.active AND t.active AND u.role IN ('owner','admin')))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
        AND updated_by::text=current_setting('cvcloud.user_id',true)
        AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.tenant_id=provider_config.tenant_id AND u.id::text=current_setting('cvcloud.user_id',true)
            AND u.active AND t.active AND u.role IN ('owner','admin')));
-- No delete policy: preserve the revision fence. No production grants here.
COMMIT;
