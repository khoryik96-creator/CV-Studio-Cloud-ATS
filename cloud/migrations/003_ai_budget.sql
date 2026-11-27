-- Monetary amounts in integer micro-US dollars, never binary floating point.
BEGIN;
ALTER TABLE cvcloud.jobs ADD UNIQUE (tenant_id,id,owner_id);
CREATE TABLE cvcloud.ai_budgets (
    tenant_id uuid PRIMARY KEY REFERENCES cvcloud.tenants(id),
    limit_microusd bigint NOT NULL CHECK (limit_microusd BETWEEN 0 AND 1000000000000),
    reserved_microusd bigint NOT NULL DEFAULT 0 CHECK (reserved_microusd >= 0),
    spent_microusd bigint NOT NULL DEFAULT 0 CHECK (spent_microusd >= 0)
);
CREATE TABLE cvcloud.ai_reservations (
    tenant_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    job_id uuid NOT NULL,
    operation_id uuid NOT NULL,
    lease_token uuid NOT NULL,
    provider text NOT NULL CHECK (provider IN ('deepseek','anthropic','openai','google')),
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
    reserved_microusd bigint NOT NULL CHECK (reserved_microusd BETWEEN 1 AND 1000000000000),
    actual_microusd bigint CHECK (actual_microusd BETWEEN 0 AND 1000000000000),
    created_at timestamptz NOT NULL DEFAULT now(),
    settled_at timestamptz,
    PRIMARY KEY (tenant_id,operation_id),
    FOREIGN KEY (tenant_id,job_id,owner_id) REFERENCES cvcloud.jobs(tenant_id,id,owner_id),
    FOREIGN KEY (tenant_id) REFERENCES cvcloud.ai_budgets(tenant_id),
    CHECK ((settled_at IS NULL) = (actual_microusd IS NULL))
);
CREATE INDEX ON cvcloud.ai_reservations (tenant_id,job_id);
ALTER TABLE cvcloud.ai_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.ai_budgets FORCE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.ai_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.ai_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_budget ON cvcloud.ai_budgets
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true));
CREATE POLICY owner_reservation ON cvcloud.ai_reservations
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
      AND owner_id::text=current_setting('cvcloud.user_id',true))
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
      AND owner_id::text=current_setting('cvcloud.user_id',true));
COMMIT;
