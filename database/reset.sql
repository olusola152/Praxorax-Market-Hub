-- Wipe the database and start clean.
--
-- DESTRUCTIVE. Every account, brief, placement, submission and file record is
-- deleted. There is no undo. Only run this on a database you are happy to lose.
--
-- After running this, run in order:
--     schema.sql
--     migration_v3.sql
--     migration_v4.sql
--     migration_v5.sql
--     migration_v6.sql
--     migration_v7.sql
--
-- Then, on your own machine:
--     python create_admin.py
--     python seed_demo.py        (optional — demo accounts)
--
-- Files already uploaded live on disk, not in here. Delete the contents of
-- your uploads/submissions/ folder too, or you will keep orphaned files.

DROP TABLE IF EXISTS
    -- v6
    portfolio_certificates,
    -- v5 / v4
    submission_confirmations, team_members, teams, deliverables, bookmarks,
    -- v3
    file_downloads, submission_files, project_applications,
    -- v2 and earlier
    certificates, assessments, reviews, notifications, submissions, milestones,
    assignments, project_requests, engagements, applications,
    project_skills, projects, lecturer_fields, student_skills, skills,
    passcodes, student_profiles, lecturer_profiles, companies, client_profiles,
    universities, fields, audit_log, messages, ratings, users
CASCADE;
