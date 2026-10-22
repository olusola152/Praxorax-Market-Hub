-- PraxoraX — migration v11
--
-- Run after migration_v10.sql. Additive.
--
-- Verifying a university, the way companies have been verified since v4.
--
-- A university registering got a live public portal at /u/<slug> immediately,
-- which meant anyone could register as "University of Lagos" and collect
-- lecturer and student signups under that name. A company cannot publish a
-- brief until an administrator has seen its registration document; an
-- institution asking students to hand over their matriculation numbers should
-- clear the same bar.

ALTER TABLE universities
    ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) NOT NULL
        DEFAULT 'pending'
        CHECK (verification_status IN ('pending','verified','rejected'));

-- What they sent to prove it: an accreditation letter, a page on the
-- institution's own domain, a .edu address. Held as a URL and a note rather
-- than a file, because the useful evidence is usually a link.
ALTER TABLE universities ADD COLUMN IF NOT EXISTS evidence_url VARCHAR(500);
ALTER TABLE universities ADD COLUMN IF NOT EXISTS evidence_note TEXT;
ALTER TABLE universities ADD COLUMN IF NOT EXISTS evidence_submitted_at TIMESTAMPTZ;

-- The decision, and who made it. Shown to the institution, so a rejection
-- has to say what was wrong.
ALTER TABLE universities ADD COLUMN IF NOT EXISTS verification_notes TEXT;
ALTER TABLE universities ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE universities
    ADD COLUMN IF NOT EXISTS verified_by INT REFERENCES users(id) ON DELETE SET NULL;

-- Institutions that were already here were admitted under the old rules and
-- are not locked out by this one. Only accounts created from now on wait.
-- This mirrors what v4 did for companies.
UPDATE universities
   SET verification_status = 'verified', verified_at = NOW()
 WHERE verification_status = 'pending' AND created_at < NOW();

CREATE INDEX IF NOT EXISTS idx_universities_unverified
    ON universities (created_at) WHERE verification_status = 'pending';
