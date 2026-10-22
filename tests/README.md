# Tests

Plain scripts, no pytest. Each one prints PASS/FAIL per check and a total.

They need a throwaway PostgreSQL database — never point them at your real one,
they insert and delete rows.

```bash
createdb smtest
psql -d smtest -f database/schema.sql
psql -d smtest -f database/migration_v3.sql
psql -d smtest -f database/migration_v4.sql
psql -d smtest -f database/migration_v5.sql
psql -d smtest -f database/migration_v6.sql
psql -d smtest -f database/migration_v7.sql
psql -d smtest -f database/migration_v8.sql
psql -d smtest -f database/migration_v9.sql
psql -d smtest -f database/migration_v10.sql

export DATABASE_URL="postgresql://postgres:PASSWORD@127.0.0.1:5432/smtest"
export SECRET_KEY=test
export UPLOAD_FOLDER=/tmp/uploads
```

| Script | Needs | Covers |
|---|---|---|
| `test_public_student_flow.py` | an **empty** database | signup on the main page, applying, the company accepting, uploading files, downloading, permissions |
| `test_all_pages.py` | `python seed_demo.py` run first | every page for every role returns 200 |
| `test_review_chain.py` | `python seed_demo.py` run first | student → lecturer → university → company, with file downloads at each step |
| `test_v4_modules.py` | an **empty** database | teams, deliverables, company KYC, bookmarks and match scoring |
| `test_v4_pages.py` | `python seed_demo.py` run first | the pages those four modules added |
| `test_v5_trial.py` | an **empty** database | the 7-day trial, its expiry, and the imagery |
| `test_v16_client_review.py` | `python seed_demo.py`, and `pip install aiosmtpd` | the three things the client asked for: inviting people who are not here yet, the profile gate, and proving email works |
| `test_v15_idle.py` | `python seed_demo.py` run first | idle sign-out: the clock, the heartbeat, the return path, and that asking the time does not reset the timer |
| `test_v14_identity.py` | `python seed_demo.py` run first | the mark, the tab icon, the hero plate and the faculty tiles: every tile well-formed, one shared ground, every field in the database covered, and no button whose text colour matches its own background |
| `test_v13_presentations.py` | `python seed_demo.py` run first | project presentations: proposing, agreeing, the join window, attendance, and who may record the outcome |
| `test_v12_admin_deck.py` | `python seed_demo.py` run first | the admin deck, the chain board, and the public students view |
| `test_v11_email.py` | `python seed_demo.py`, and `pip install aiosmtpd` | email alerts, against a real SMTP server on localhost — nothing mocked |
| `test_v10_missing_files.py` | `python seed_demo.py` run first | downloads when a file record outlives its file |
| `test_v9_full_chain.py` | `python seed_demo.py` run first | the entire journey: submit → supervisor → university → company → completed → portfolio → certificate → verified |
| `test_v8_one_click.py` | `python seed_demo.py` run first | one-click project requests and `clear_placements.sql` |
| `test_v7_phase_signoff.py` | `python seed_demo.py` run first | signing a phase off from the review page and the alerts it sends |
| `test_v6_portfolio.py` | an **empty** database | the rename, the portfolio, public sharing, the consolidated certificate and verification |

Run one with:

```bash
PYTHONPATH=. python tests/test_public_student_flow.py
```

`test_public_student_flow.py` deliberately runs with `DEMO_MODE=false`, so a pass
proves independent students work with no subscription anywhere.
