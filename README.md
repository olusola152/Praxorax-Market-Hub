# PraxoraX

Flask + Supabase (PostgreSQL). Universities and companies subscribe. Companies
post briefs in a field of study; lecturers with that expertise apply to
supervise; once approved they place their own students and monitor the work
through four phases to the deadline. Students browse and build portfolios but
never apply directly.

## Roles

| Role | Gets in by | Can do |
|---|---|---|
| **Student** | Free signup on their university's portal | Browse projects, submit work, keep a GitHub portfolio. Cannot apply. |
| **Lecturer** | Passcode, on their university's portal | See projects matching their expertise, apply, place students, monitor phases |
| **University** | Self-signup, admin activates subscription | Issue lecturer passcodes, see all lecturers/students/placements |
| **Company** | Self-signup, admin activates subscription | Post projects, approve lecturers, watch progress |
| **Admin** | `create_admin.py` only | Platform-wide oversight — see below |

## Setup

1. **Tables** — Supabase → SQL Editor → paste `database/schema.sql` → Run.
   It drops the old v1 tables first.
2. **Connection string** — Supabase → Connect → Session pooler (port 5432).
3. **`.env`** — copy `.env.example` to `.env`, fill in both values.
4. **Run**

   ```
   pip install -r requirements.txt
   python create_admin.py
   python app.py
   ```

## First run, in order

1. Sign in as admin.
2. Register a **university** at `/register` (sign out first). Back as admin →
   Subscriptions → set it **active**.
3. As the university, the dashboard shows your portal link,
   `/u/your-institution-name`, plus direct links for each route.
4. Under Passcodes, generate one. **Copy it — shown once.**
5. Send each lecturer their code and the lecturer link. Students use the
   student link — lecturers can forward it to their classes. Everyone signs in
   afterwards at the portal.
6. Register a **company**; admin activates it; post a project in a field.
7. As the lecturer: Find projects → apply. As the company: approve.
8. As the lecturer: place students → monitor phases.
9. As a student: open the placement, submit a GitHub link.

## How work flows

No money changes hands for projects — every brief is practical experience.
Subscriptions are the only payment, and they are between the platform and the
institution or company.

1. **Company posts a brief** — title, description, deliverables, field of
   study, deadline, number of places. No amount, no bidding.
2. **A lecturer asks for it** — any open brief, not only ones matching their
   expertise. Briefs in their registered fields are simply listed first. The
   request says how the students will approach it and how many places are needed.
3. **The company approves or declines.** Nobody is placed until they approve,
   and the lecturer can never assign more students than the places granted.
4. **The lecturer assigns students** — their own, at their own institution.
   Each placement gets four phases spread to the deadline, and the student is
   notified immediately.
5. **The student builds it** and submits a repository link.
6. **The work travels up the chain**: student → lecturer → university →
   company. Each holder can pass it on with a comment, or send it back for
   correction, which returns it to the student.
7. **The company approves**, a certificate is issued, and the project appears
   in the student's profile.

A student cannot submit again while a version is still under review, and a
correction request from any level reopens submission.

## University portals

Each university gets a public page at `/u/<slug>` — its advertisement, with
student signup, lecturer signup (passcode required) and sign-in. The
university's private control panel is at `/university/dashboard`, labelled
**Admin**.

The main site at `/` is a public landing page explaining the platform, with
subscribe buttons for universities and companies.

## What a lecturer sees of their students

**Lecturer → Students** lists everyone registered under the same institution:
name, email, faculty, course, level, matric number, GitHub link, how much work
they have on, how many placements are with this lecturer, and certificates
earned. Students studying one of the lecturer's own areas of expertise are
listed first and flagged; the filter defaults to those and can be widened to
the whole institution. A lecturer never sees students from another university.

## When a subscription expires

`subscribed_until` is checked on every read, so expiry needs no scheduler.
Once past that date:

- the institution's portal shows "X's subscription has expired" and closes
  both signup routes and portal sign-in
- students and lecturers of that institution see a red banner and cannot
  assign, submit or forward anything
- existing data is untouched and becomes available again on renewal
- companies are gated the same way: no posting while expired

## The platform admin

One account oversees the whole site. It belongs to no university and no
company, and sees across all of them:

| Page | Shows | Can do |
|---|---|---|
| Dashboard | Totals for every role, pending activations, recent signups and actions | — |
| Users | Every account, filterable by role, with organisation and last login | Block / unblock with a reason |
| Universities | Every institution, its lecturers, students, open codes, placements | Set subscription, block the account |
| Companies | Every company, its projects and placements | Set subscription, block the account |
| Projects | Every brief on the platform, filterable by status | Cancel a draft or open brief |
| Placements | Every student on every project, with overdue phases flagged | — |
| Activity | The full audit log | — |

Admins cannot block themselves or other admins. Cancelling only applies to
draft and open briefs — once a project is engaged, students are working on it,
so pulling it is not a one-click action.

## Trying it before anyone pays

Two ways to get a working system without going through activation.

**Demo mode.** Put `DEMO_MODE=true` in `.env` and restart. Registration opens
on every portal regardless of subscription, and every subscription check is
bypassed, so a lecturer can apply and a company can post immediately. A brass
banner appears on every page while it is on. Turn it off before going live —
with it on, anyone who finds the site can register and post.

**Demo data.** `python seed_demo.py` fills the database with a university whose
subscription is already active, two lecturers, six students, two companies and
four projects — one of them already engaged, with students placed, phases
part-completed and a GitHub submission in place. Every page then has something
real on it.

Every seeded account uses the password `demo1234` and an email ending in
`@demo.marketplace`. The script prints the full list plus two unused lecturer
passcodes so you can walk the registration flow by hand. Re-running it removes
and rebuilds only its own accounts — your admin and anything you created
yourself are untouched.

Delete `seed_demo.py` before deploying, or at minimum never run it against a
live database.

## Security

- Passwords and passcodes are both hashed. A leaked database yields no
  working codes.
- Passcodes are single-use, expire in 14 days, and are consumed inside the
  registration transaction, so two people racing the same code cannot both win.
- Lecturers only ever see projects in their declared fields — enforced in SQL,
  not by hiding links.
- A lecturer can only place students from their own university and field.
- Subscription checks gate the paid actions; read-only pages stay open so an
  expired account can still see its data.
- Blocked accounts are signed out on their next request and cannot log in.
- Admins cannot block themselves or other admins.
- Every block, unblock, subscription change and passcode batch is written to
  `audit_log`.

## Not built yet

- **Payment** — subscriptions are activated by an admin after payment clears
  out of band. Flutterwave integration is the obvious next step, and needs a
  decision on whether project rewards are held in escrow or paid direct.
- **Assessment and certificates** — the tables exist; scoring a submission and
  issuing a certificate is the next feature.
- **File uploads** — submissions take a repository link. Uploaded files would
  need Supabase Storage, since hosts wipe local disks on restart.
- **Email** — passcodes are shown on screen, not emailed.

## Deployment

Not Netlify — it cannot run Python. `Procfile` and `render.yaml` are included,
so Render works out of the box: connect the repository, and it reads the build
command, start command and health check from `render.yaml`.

Set these environment variables on the host:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase session pooler URI, port 5432 |
| `SECRET_KEY` | 64 random hex characters. Render can generate it |
| `SECURE_COOKIES` | `true` once the site is on HTTPS |

**Before going live:**

- Set `SECURE_COOKIES=true`. Without it the session cookie is sent over plain
  HTTP as well.
- Remove or restrict `create_admin.py` on the server. Anyone with shell access
  can otherwise mint an administrator.
- Rotate `SECRET_KEY` away from any value used in development. Changing it
  signs everyone out, which is the point.
- Take a Supabase backup before the first real users arrive.

**What is already handled:** `ProxyFix` so the real client address and scheme
survive the load balancer; a `/healthz` probe that does not touch the database;
sign-in throttling per address (8 failures, then a five-minute cooldown,
configurable); an upload cap with its own error page; and a refusal to start at
all if `SECRET_KEY` is missing, rather than falling back to a default.

**Known limits.** Throttling is per process and in memory — run more than one
web worker process and each keeps its own count; move it to the database or
Redis if that matters. There is no password reset flow yet, no email, and
subscriptions are still activated by hand.

---

## Update — independent students, project files, and downloads

Three changes, all additive. Nothing about the existing university flow moved:
a lecturer still requests a brief, the company still approves, the lecturer
still places their own students, and work still travels
student → lecturer → university → company.

### 1. Anyone can join as a student on the main page

`/register` now offers **Student** beside Company and University. Someone who
signs up there has no university behind them — `student_profiles.university_id`
is left NULL, and that single fact is what marks the account as independent
everywhere else in the code.

An independent student pays nothing and belongs to no subscription. They browse
the open briefs and **apply to the company themselves**. The company accepts or
declines at `/company/applications`. Once accepted, the placement is created
with `lecturer_id` NULL and `source='direct'`, and the student's work goes
straight to the company — no lecturer, no university in the chain.

Lecturers still join only through their own institution's portal, because a
lecturer needs a passcode from that institution to prove who they are.

Turn the whole thing off with `OPEN_STUDENT_SIGNUP=false`.

### 2. Students upload the actual project, not just a link

Submitting used to require a GitHub or GitLab URL. Now a student can attach
files instead, or as well. Each file is written to disk under:

    uploads/submissions/<assignment_id>/v<version>/<generated-name>

and a row in `submission_files` records the original name, the size, the MIME
type, a SHA-256 checksum, who uploaded it and when. The name on disk is
generated, never the one the browser sent.

Limits live in `storage.py`: 32 MB a file, 96 MB a submission. Program files
(`.exe`, `.bat`, `.sh`, `.js`, and the rest) are refused outright — anything
unusual should go inside a `.zip`.

### 3. Downloading

`/files/<id>` streams one file under its original name. `/files/submission/<id>/archive`
zips the whole version. Both are guarded by one rule, in
`workflow.can_access_submission`: only the people on that placement's chain may
read it — the student, their lecturer, that lecturer's university, the company
that owns the brief, and admins. Everyone else gets a 403. Every download is
written to `file_downloads`, so a company can show it collected the work and a
student can see who took a copy.

### 4. The project record

`/student/placements/<id>/record` is the page to open when someone asks what was
delivered and when. Brief posted, published, joined, deadline, completed;
every phase with its due date; every submitted version with its files,
checksums, notes and the full review trail; and the certificate if one was
issued.

`projects` gained `published_at`, `completed_at` and `updated_at`, stamped as
briefs are published and finished.

### Applying this update

```sql
-- in the Supabase SQL editor, on top of your existing database
-- database/migration_v3.sql
```

It is additive: no DROP, no data loss. Then:

```bash
pip install -r requirements.txt
python app.py
```

Uploads land in `./uploads` unless you set `UPLOAD_FOLDER`. **On Render's free
tier the disk is wiped on every redeploy** — attach a persistent disk, or move
file storage to Supabase Storage, before anyone relies on it.

### What is not in here

The client's PRD describes GradLinq, which is Next.js, NestJS, GraphQL and
Drizzle with subdomain routing. That codebase cannot be merged into a Flask
app. What is above is the set of features from that document your build was
missing. Still absent, and each a separate piece of work: OTP signup and
passwordless login, teams, the AI CV, semantic project matching, in-app
messaging, and company KYC verification in the admin panel.

---

## Update — teams, deliverables, verification, saved briefs

Additive again. Run `database/migration_v4.sql` after v3. Nothing is dropped.

### Teams

A student creates a team and becomes its lead; everyone else joins by
invitation, and the invitee must already have an account here. Up to six
people. The lead applies for a brief on the team's behalf, and if the company
accepts, **every active member gets their own placement row** tied to the same
team — so the existing review chain, milestones and certificates all keep
working untouched.

Team work does not leave the team until everyone signs off. One member prepares
a submission; it sits at `awaiting_team` while the others confirm. All confirm →
it moves on to the lecturer, or straight to the company for independent
students. **One rejection** sends the whole thing back to `changes_requested`,
rather than letting a majority overrule a member who spotted a problem.

Membership is frozen once a team is placed on a brief. Nobody can be added,
removed, or leave mid-project.

### Deliverables

The four fixed phases in `milestones` still exist and still drive the progress
bars. Deliverables sit beside them: a supervising lecturer, or the company that
owns the brief, writes their own named pieces of work with their own due dates
at `/deliverables/project/<id>`.

A deliverable is invisible to students while it is a draft. Publishing it
notifies everyone on the brief. A published deliverable cannot be deleted, only
archived, and a due date after the brief's own deadline is refused.

Students pick a deliverable when submitting, or leave it blank for general
progress — which is what every existing submission does, so nothing breaks.

### Company verification (KYC)

Companies now start at `verification_status = 'pending'` and **cannot publish a
brief** until an administrator verifies them. They can still draft. The company
submits a link to its registration document at `/company/verification`; an
admin reviews it at `/admin/kyc` and either verifies or rejects with a written
reason the company sees.

Companies that already existed when the migration ran are marked verified, so
this changes nothing for them. Only new signups start pending.

Both routes into publishing are gated — the publish button and the "publish
immediately" checkbox on the create form.

### Saved briefs and match scoring

Students tick their skills on their profile. Every brief in the feed is then
scored against them in `matching.py`: 70% of the score is how much of the
brief's required skills the student covers, 30% is Jaccard overlap. Anything
at or above 0.30 shows a label. `/student/projects?sort=match` sorts by it.

Deliberately simple and transparent — a student can see why a number came out
the way it did, and it needs no external service. The PRD's semantic matching
would replace the body of `matching.score` and nothing else would change.

Bookmarks are a plain toggle, listed at `/student/bookmarks`.

---

## Update — free trial and imagery

Run `database/migration_v5.sql` after v4. Additive as always.

### The free week

A university or company that signs up now lands on
`subscription_status = 'trial'` with `subscribed_until` seven days out, set by
`TRIAL_DAYS` in `.env`. No payment, no card, and no administrator has to do
anything.

A trial and a paid subscription are treated as **the same thing** while they
last — `subscription_live()` accepts both, so no feature has to ask which one
it is looking at. A trial that quietly did less would be a poor trial.

It expires exactly the way a paid term does: `effective_status()` checks the
date on read, so nothing depends on a scheduler being alive, and
`expire_lapsed()` writes the expiry back so admin lists match reality. A
countdown banner sits at the top of every page while the trial runs, and turns
blunt on the last day.

Two things the trial deliberately does **not** unlock. Company verification
still applies — a trial company can draft briefs but not publish them until an
admin verifies it, because the trial proves nothing about who they are. And
`trial_started_at` records that a free week was taken, so a second one cannot
be opened on the same account.

Independent students are untouched by all of this. They never had a
subscription, so there is nothing to trial — their side is simply free.

### Imagery

`static/img/` ships vector artwork: a landing-page hero, and one tile per
curriculum field. The feed, the saved list and the brief detail page all show
cover art now, picked in this order:

1. `projects.cover_url` — a real photo the company set
2. `fields.image_url` — the field's tile
3. `img/brief-placeholder.svg`

So a brief always has something to look at, and a real photograph takes over
the moment one is set. New URL columns: `companies.logo_url`,
`universities.logo_url`, `projects.cover_url`, `student_profiles.avatar_url`,
`fields.image_url`.

These are drawings, not photographs — I cannot supply stock photos, and fake
ones would look worse than honest geometry. `static/img/README.md` explains
how to drop real images in; it is one `UPDATE` per field, or a URL in the
brief form.

The landing page is rebuilt around this: a split hero with the artwork, a
faculty tile row, and a closing band selling the free week.

---

## Starting the database over

`database/reset.sql` drops every table this app owns. It is destructive and
there is no undo — only run it on a database you are happy to lose.

In the Supabase SQL editor, run in this order:

```
database/reset.sql
database/schema.sql
database/migration_v3.sql
database/migration_v4.sql
database/migration_v5.sql
```

Then on your machine:

```bash
python create_admin.py     # your own admin account
python seed_demo.py        # optional demo accounts, password demo1234
```

Uploaded files live on disk, not in the database, so empty
`uploads/submissions/` as well or you will keep orphaned files no row points at.

`schema.sql` carries the same DROP list, so re-running it alone also starts
clean. Both lists are kept in step with every migration — if you add a table in
a future migration, add it to both.

---

## Update — PraxoraX, portfolios and certificates

Run `database/migration_v6.sql` after v5.

### The rename

The product is now **PraxoraX**. Every user-facing string reads
`Config.BRAND`, so renaming again is one line in `.env` rather than a hunt
through templates.

This rename turned up a bug shipped in the previous build: the trial call-to-action
section had been inserted inside `{% block title %}` on the landing page, so it
was rendering into the `<title>` tag. Tests passed because the text was still
present in the HTML. Fixed, and the test now checks the band appears *after*
`</title>`.

### Student portfolio — `/student/portfolio`

Every placement a company has signed off, newest first. Only approved work
appears; a portfolio listing half-finished projects would be worth nothing to
an employer.

Each entry carries the brief, the company, the field and faculty, the
difficulty, when the student started and finished, how many days it took, how
many versions and files they submitted and when the last one landed, whether
they worked alone or on a named team, whether they were placed by a lecturer or
applied directly, who supervised, and the per-project certificate number.

Above the list: projects completed, companies worked for, certificates held,
versions submitted, files delivered, typical project length, and every skill
touched.

### Public sharing — `/p/<token>`

A student can generate an unguessable public link and hand it to an employer
instead of a login. The public view shows finished work only — no email
address, no placements in progress, no controls. Turning sharing off destroys
the token, so the old link dies for good.

### Consolidated certificate

`/student/portfolio` → **Generate a certificate**. It covers everything
completed as of that moment, with a reference like `PX-1A2B3C4D5E`.

The certificate stores a **frozen snapshot** of what it said when issued. A
student may finish three more projects next month; a certificate handed to an
employer today should still say what it said today. Verification reads the
snapshot, not the live tables — the test proves this by renaming a project
afterwards and checking the certificate is unchanged.

It is a print-styled page rather than a generated PDF. `Ctrl+P` → Save as PDF
gives a clean document with no navigation or banners. That avoids adding a PDF
library, which on Windows and Python 3.14 is a real installation risk for no
gain the student would notice.

### Verification — `/verify`

Anyone can paste a reference and check it, with no account. Works for both the
consolidated certificates and the per-project ones a company issues on sign-off.
Revoked certificates say so plainly.

---

## Update — phase sign-off

Run `database/migration_v7.sql` after v6.

### The problem

A supervisor had two buttons on the review page: pass it up the chain, or ask
for corrections. There was no way to say "this phase is fine" — so a student
whose work was good heard nothing, and had to read silence as approval. Phases
could be marked done on the lecturer's monitor page, but the student was never
told, and the student cannot see that page.

### What changed

The review page gains a third action: **Satisfied — no corrections needed**.
Pick a phase, add an optional note, and it is signed off. The submission does
not move — this is for when a supervisor is happy with one phase but is not
ready to pass the whole thing on.

Every phase change now alerts the student, from the review page and the monitor
page alike, naming the phase and carrying the note. Marking a phase back to
in-progress or pending alerts them too, because a phase quietly reopening is
worse than one quietly closing.

The student's placement page states it outright — "Signed off by Dr Bello on
14 Mar 2026, 15:20 — no corrections needed" — rather than leaving them to infer
it from a status chip. `milestones` now records `signed_off_by` and
`signed_off_at`, and the decision appears in the review trail as
`phase_satisfied` against that phase, so the history shows what was approved
and not just that something was.

### Also fixed

A blank `UPLOAD_FOLDER=` line in `.env` crashed every file upload with
`FileNotFoundError: ''`. `os.environ.get` returns an empty string for a blank
value rather than the default, so the app tried to create a directory named
`""`. It now falls back properly. The tests never caught this because they
always set a real path — a gap in the tests as much as in the code.

### Fixed — the dead certificate button

The Generate a certificate button carried a `disabled` attribute when a
student had no completed projects. A disabled button produces no click, no
submit and no message, so it looked broken rather than unavailable.

The button is now simply absent when there is nothing to certify, replaced by
an explanation: a project counts once the company has approved the final
submission — not when it is sent, and not while it is under review. Below
that, every placement still in flight is listed with its stage in plain words
("with your supervisor", "with the company"), so the student can see exactly
where the hold-up is.

No template should ever render a disabled control with no explanation beside
it. That was the real mistake.

---

## Update — one-click requests, and a reset for testing

No migration. Replace the files and carry on.

### Requesting a brief is now one click

A lecturer had to write at least 40 characters and pick a place count before
they could express interest. That is a form standing between two parties who
just want to say yes to each other, so it is gone.

The button now appears on the browse list as well as the brief itself. One
click sends the request, defaults to one place, and notifies the company, who
accept or decline at `/company/requests` exactly as before. A note and a larger
place count still exist, behind a disclosure marked "Add a note or ask for more
places" — available when there is something to say, never in the way.

Asking twice is still refused, and the company's decision still gates
everything: no student is placed until they approve.

### `database/clear_placements.sql`

Puts every brief back to unassigned without touching the accounts. Placements,
submissions, file records, phases, reviews, requests, applications, teams,
certificates and notifications all go; users, universities, companies, briefs,
skills and fields all stay.

For walking the flow from the start when test data has got tangled — which is
most of the time while building. Unlike `reset.sql`, you do not have to re-run
the schema or re-seed afterwards.

Uploaded files live on disk, so empty `uploads/submissions/` as well.

---

## Update — knowing where your work has got to

No migration. Replace the files.

### The problem

A student who submitted, and whose supervisor then forwarded the work, still
saw the same flat refusal on the submit form: *"Your last submission is still
being reviewed."* True, but useless. It never said who was holding it, so a
supervisor forwarding the work looked identical to a supervisor ignoring it,
and the whole thing read as broken.

### What changed

While the chain holds a version, the submit form is replaced by a panel saying
exactly where it is — *"Version 3 is with the university"* — with the date it
was sent and a three-step strip showing Supervisor → University → Company, the
current holder marked.

The refusal message, if someone posts anyway, now names the version and the
holder and says what unblocks it: *"Version 3 is with the university at the
moment. You can send a new version once they respond."*

The block itself stays. Two live versions would leave three reviewers arguing
over which one is current. Requesting corrections releases it, and the form
comes straight back.

### Proved end to end

`tests/test_v9_full_chain.py` walks the entire journey the way a person does:
student submits source and a guide together → supervisor forwards → university
forwards → company approves → placement completes → the per-project certificate
is issued → the portfolio fills → the consolidated certificate generates → a
stranger verifies its reference. It also checks what the student sees at each
stage, and that requesting corrections reopens the form. 30 checks, all passing.

---

## Update — when a file goes missing

No migration. Replace the files.

### Keep uploads outside the project folder

Set this in `.env`, and do it before anything else:

```
UPLOAD_FOLDER=C:\praxorax-uploads
```

Submitted files live on disk, not in the database. If they sit inside the
project folder, replacing that folder with a new build deletes every file
students have sent while the database rows survive — and downloads start
returning `410 Gone`.

Files already lost cannot be recovered. They have to be submitted again.

### A 410 that explains itself

The bare "Gone" page said nothing. It now states that the file is recorded but
no longer on the server, that it must be uploaded again, and how to stop it
recurring.

### One missing file no longer costs the whole archive

`Download everything as a .zip` used to fail outright if any single file was
missing. It now skips what is gone and zips what survives, and only returns
410 when nothing at all is left.

### `check_uploads.py`

Run it when a download returns 410:

```bash
python check_uploads.py
```

It lists every file record whose file is missing — the project, the version,
who sent it and when — so you know exactly what has to be re-submitted. Reads
only; changes nothing.

---

## Update — email alerts

Run `database/migration_v8.sql` after v7.

### Why not Supabase

Supabase cannot send these. Its email service only covers auth mail —
confirmations, magic links, password resets — and exposes no API for sending
arbitrary messages. Routing through an Edge Function to a mail provider would
work, but it adds a hop for nothing, since this app is already a server that
can send mail itself. `mailer.py` talks to SMTP directly.

### Setting it up

In `.env`:

```
BASE_URL=https://your-real-domain.com     # links in emails are built from this
MAIL_ENABLED=true
MAIL_HOST=smtp.gmail.com
MAIL_PORT=587
MAIL_USER=you@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_FROM=you@gmail.com
MAIL_STARTTLS=true
```

Gmail needs an **App Password**, not your account password, and two-factor
must be on before you can create one. Zoho uses port 465 with
`MAIL_SSL=true` and `MAIL_STARTTLS=false`.

Check it works before relying on it:

```bash
python send_test_email.py you@example.com
```

It sends one message synchronously and prints the exact failure if there is
one, rather than failing quietly the way a background send does.

### How it behaves

Every in-app alert is emailed too: placements, submissions, corrections with
the reviewer's reason included, phase sign-offs, applications, team
invitations, approvals and certificates.

Three rules it follows:

* **Never blocks a request.** Mail goes out on a background thread, so a slow
  or dead SMTP server cannot make anyone wait for a page.
* **Never breaks the app.** The notification row is written first and is never
  conditional on the email. A refused send is logged and dropped;
  `notifications.emailed_at` stays NULL, so you can tell later whether a
  message was sent or never attempted.
* **Never mails someone who said no.** Each account has a switch on its
  notifications page, on by default.

Emails go out as plain text and HTML together, so they read properly in every
client, and each one says how to turn them off.

### Also fixed

A "corrections requested" alert said only that corrections were requested. The
reviewer had already typed the reason; it now travels with the alert, and
therefore into the email. Being told to fix something without being told what
was the most useless message in the app.

`BASE_URL` was missing from config entirely — added, since every link inside an
email is built from it.

### Welcome emails

Signing up sent nothing. Emails only fired on events that happen once you are
already inside, so the first message anyone got was about someone else's work.

Every signup path now sends one — the main page, and both university portal
paths — and each says what that role actually does next. A student is told to
browse and apply; a company is told its trial has started and that a brief
cannot go live until verification; a university is told to issue lecturer
passcodes; a lecturer is told to request briefs and place students.

It goes out directly rather than through `notify()`, because there is no
in-app equivalent of "welcome" and nothing to link to beyond the dashboard.

If you set up email mid-project, existing accounts get nothing — the message
fires at signup, and theirs has passed.

### Note on ports

Gmail's port 587 is blocked on many Nigerian networks. If `send_test_email.py`
times out, use 465 instead:

```
MAIL_PORT=465
MAIL_SSL=true
MAIL_STARTTLS=false
```

All three lines matter. Port 465 expects SSL from the first byte and no
STARTTLS; leaving STARTTLS on makes Gmail drop the connection with
"Connection unexpectedly closed". This is a network restriction, not a code
problem — 587 will work again once deployed.

---

## Deploying

`DEPLOY-WHOGOHOST.md` covers cPanel hosting (WhoGoHost / GO54) step by step.
`passenger_wsgi.py` is the entry point cPanel needs — point Setup Python App at
that file, never at `app.py`, which cPanel overwrites on creation.

`preflight.py` checks a server before you trust it with real users: Python
version, configuration, whether the database port is reachable *from that
server*, whether the upload folder is writable, whether the mail port is open,
and whether every table exists. Each failure says what to do about it.

```bash
python preflight.py
```

The code runs on Python 3.8 upward, so older cPanel Python versions are fine.

The real risk on shared hosting is outbound ports: the app needs 5432 to
Supabase and 465 or 587 for mail, and shared hosts often block both. Ask
support before paying — "does your Python hosting allow outbound TCP on port
5432 to an external PostgreSQL server?" — and run `preflight.py` the moment you
have access.

---

## Update — the admin deck, and public students

No migration. Replace the files.

### Why admin looks different now

The rest of PraxoraX is sage paper: a record you could print and file. That
suits a student reading their portfolio or a company reading a submission.

Administration is a different job. Nobody reads records there — they watch a
system move and decide what is stuck. So admin now has its own visual language:
dark, dense, instrument-like, navigated from one fixed rail instead of a row of
nine links that wrapped awkwardly. The colour vocabulary carries over — brass
for anything needing a human, seal green for anything settled — so it reads as
the same product seen from backstage.

### The chain board

The first thing on `/admin/dashboard` is not a count of users. It is where
submitted work is sitting right now: waiting on teammates, with supervisors,
with universities, with companies, or back for corrections. That is the one
view that says whether the platform is moving or jammed.

Under it, **Held up** lists submissions that have sat with one reviewer for
more than a week. Every row is a student waiting on somebody. This is the thing
an administrator should act on, so it is on the first screen rather than buried.

Then the counts that need a decision — companies to verify, subscriptions to
activate, requests and applications still open — each linking to where the
decision is made. Signups are drawn as a twelve-week line.

### Public students — `/admin/public-students`

Students who joined on the main page with no university behind them are a
different population: nobody supervises them, nobody vouches for them, and no
subscription covers them. Burying them in the general user list hid that.

They now have their own view, split four ways: all, on a brief, waiting to hear
back, and signed up but never applied. Each row carries their field, skills
listed, applications, placements, projects finished and last submission date.

The fourth filter is the useful one. A climbing "never applied" number while
briefs sit open usually means the briefs being posted do not match what
students can actually do — worth comparing the fields companies post against
the fields students list.
