-- Student & Client Marketplace — migration v5
--
-- Run after migration_v4.sql. Additive; nothing is dropped.
--
--   1. Free trial — a university or company gets 7 days on signup, with no
--      payment and no admin step. Independent students are unaffected: they
--      never had a subscription to begin with.
--   2. Images — logos and cover art, so the site can look like a product
--      rather than a form.

-- --------------------------------------------------------------- 1. trial

-- 'trial' joins the allowed values on both tables.
ALTER TABLE universities DROP CONSTRAINT IF EXISTS universities_subscription_status_check;
ALTER TABLE universities ADD CONSTRAINT universities_subscription_status_check
    CHECK (subscription_status IN ('pending','trial','active','expired','suspended'));

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_subscription_status_check;
ALTER TABLE companies ADD CONSTRAINT companies_subscription_status_check
    CHECK (subscription_status IN ('pending','trial','active','expired','suspended'));

-- When the free week started. NULL means they never took one, which is how
-- the app stops a second trial being opened on the same account.
ALTER TABLE universities ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;
ALTER TABLE companies    ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;

-- ---------------------------------------------------------------- 2. images

ALTER TABLE companies    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500);
ALTER TABLE universities ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500);
ALTER TABLE projects     ADD COLUMN IF NOT EXISTS cover_url VARCHAR(500);
ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);

-- Curriculum areas get artwork so the feed is not a wall of text. These point
-- at files shipped in static/img/fields/, and can be repointed at anything.
ALTER TABLE fields ADD COLUMN IF NOT EXISTS image_url VARCHAR(500);

UPDATE fields SET image_url = 'img/fields/' ||
    lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g')) || '.svg'
 WHERE image_url IS NULL;
