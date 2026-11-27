BEGIN;
ALTER TABLE cvcloud.jobs ADD COLUMN alignment text NOT NULL DEFAULT 'left' CHECK (alignment IN ('left','justify'));
ALTER TABLE cvcloud.jobs ADD COLUMN correct_language boolean NOT NULL DEFAULT false;
ALTER TABLE cvcloud.jobs ADD COLUMN neutral_gender boolean NOT NULL DEFAULT false;
ALTER TABLE cvcloud.jobs ADD CHECK (NOT neutral_gender OR module='cv_blinding');
COMMIT;
