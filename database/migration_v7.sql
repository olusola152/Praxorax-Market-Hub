-- PraxoraX — migration v7
--
-- Run after migration_v6.sql. Additive.
--
-- Lets a supervisor say "this phase is fine, no corrections needed" from the
-- review page, and records it in the same trail as every other decision, so
-- the student sees it beside the comments rather than having to infer it from
-- silence.

-- 'phase_satisfied' joins the actions a review can record.
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_action_check;
ALTER TABLE reviews ADD CONSTRAINT reviews_action_check
    CHECK (action IN ('forward','approve','request_correction','phase_satisfied'));

-- Which phase a review was about, when it was about one.
ALTER TABLE reviews
    ADD COLUMN IF NOT EXISTS milestone_id INT REFERENCES milestones(id) ON DELETE SET NULL;

-- Who signed the phase off and when. status already carries 'done'; these say
-- by whom, which matters when a student asks why something was marked complete.
ALTER TABLE milestones
    ADD COLUMN IF NOT EXISTS signed_off_by INT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE milestones
    ADD COLUMN IF NOT EXISTS signed_off_at TIMESTAMPTZ;

-- Existing completed phases have no signer on record; leave them NULL rather
-- than inventing one.
