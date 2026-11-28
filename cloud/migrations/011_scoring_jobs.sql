BEGIN;
-- These fields inherit the existing jobs table's owner and tenant policies.
ALTER TABLE cvcloud.jobs
    ADD COLUMN scoring_jd_id uuid,
    ADD COLUMN scoring_criteria jsonb,
    ADD COLUMN scoring_result jsonb,
    ADD FOREIGN KEY (tenant_id, scoring_jd_id, owner_id)
        REFERENCES cvcloud.documents (tenant_id, id, owner_id),
    ADD CHECK ((scoring_jd_id IS NULL) = (scoring_criteria IS NULL)),
    ADD CHECK (scoring_jd_id IS NULL OR module = 'cv_scoring'),
    ADD CHECK (scoring_result IS NULL OR (scoring_jd_id IS NOT NULL AND state = 'succeeded'));
COMMIT;
