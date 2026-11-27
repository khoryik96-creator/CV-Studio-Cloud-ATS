BEGIN;
-- Changing permissions must invalidate credentials checked before that change.
CREATE OR REPLACE FUNCTION cvcloud.bump_credential_version() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog AS $body$
BEGIN
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash OR NEW.active IS DISTINCT FROM OLD.active
        OR NEW.role IS DISTINCT FROM OLD.role THEN
        NEW.credential_version := OLD.credential_version + 1;
    END IF;
    RETURN NEW;
END;
$body$;
CREATE TABLE cvcloud.account_audit (
    tenant_id uuid NOT NULL,
    event_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    target_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('create','role_change','suspend','reactivate','password_reset','revoke_sessions')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,event_id),
    FOREIGN KEY (tenant_id,actor_id) REFERENCES cvcloud.users(tenant_id,id),
    FOREIGN KEY (tenant_id,target_id) REFERENCES cvcloud.users(tenant_id,id)
);
ALTER TABLE cvcloud.account_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvcloud.account_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY account_audit_read ON cvcloud.account_audit FOR SELECT
    USING (tenant_id::text=current_setting('cvcloud.tenant_id',true)
      AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
        WHERE u.tenant_id=account_audit.tenant_id AND u.id::text=current_setting('cvcloud.user_id',true)
        AND u.role IN ('owner','admin') AND u.active AND t.active));
CREATE POLICY account_audit_insert ON cvcloud.account_audit FOR INSERT
    WITH CHECK (tenant_id::text=current_setting('cvcloud.tenant_id',true)
      AND actor_id::text=current_setting('cvcloud.user_id',true)
      AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
        WHERE u.tenant_id=account_audit.tenant_id AND u.id=account_audit.actor_id
        AND u.role IN ('owner','admin') AND u.active AND t.active));
-- Append-only under ordinary runtime access; production grants separate.
COMMIT;
