-- Put every brief back to unassigned, keeping the accounts and the briefs.
--
-- Use this while testing, when the data has got tangled and you want to walk
-- the flow from the start again. Accounts, universities, companies, briefs,
-- skills and fields all survive. Everything that represents work in progress
-- is removed.
--
-- DESTRUCTIVE for: placements, submissions, uploaded file records, phases,
-- reviews, requests, applications, teams, certificates and notifications.

BEGIN;

-- Work and everything hanging off it. Order matters: children first.
DELETE FROM submission_confirmations;
DELETE FROM file_downloads;
DELETE FROM submission_files;
DELETE FROM reviews;
DELETE FROM submissions;
DELETE FROM milestones;
DELETE FROM certificates;
DELETE FROM portfolio_certificates;
DELETE FROM assignments;

-- Nobody has asked for anything yet.
DELETE FROM project_requests;
DELETE FROM project_applications;

-- Teams go back to being groups with no brief attached.
DELETE FROM team_members;
DELETE FROM teams;

-- Optional: uncomment to clear deliverables a supervisor had written.
-- DELETE FROM deliverables;

-- Every published brief is open again and has nobody on it.
UPDATE projects
   SET status = CASE WHEN status = 'draft' THEN 'draft' ELSE 'open' END,
       completed_at = NULL,
       updated_at = NOW();

-- A clean slate for alerts too, so the bell reflects what happens next.
DELETE FROM notifications;

COMMIT;

-- Uploaded files live on disk, not in here. Empty uploads/submissions/ too.
