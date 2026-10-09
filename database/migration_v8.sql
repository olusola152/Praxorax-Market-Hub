-- PraxoraX — migration v8
--
-- Run after migration_v7.sql. Additive.
--
-- Email alerts. Every in-app notification can also go out by email, and each
-- account can switch that off.

-- On by default: someone who has just been placed on a project, or asked for
-- corrections, needs to hear about it without logging in to check.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN NOT NULL DEFAULT TRUE;

-- Whether a given alert was emailed, and when. Useful when someone says they
-- never got one — you can tell whether it was sent or never attempted.
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS emailed_at TIMESTAMPTZ;
