BEGIN;
ALTER TABLE cvcloud.jobs
    ADD COLUMN report_options jsonb,
    ADD COLUMN report_result jsonb,
    ADD CHECK (report_options IS NULL OR module IN ('blind_jd', 'company_profile')),
    ADD CHECK (report_result IS NULL OR (report_options IS NOT NULL AND state = 'succeeded'));
COMMIT;
