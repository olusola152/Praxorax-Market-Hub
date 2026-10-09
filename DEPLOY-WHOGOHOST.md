# Deploying to WhoGoHost (GO54)

WhoGoHost runs Flask through cPanel's **Setup Python App**, which uses Phusion
Passenger rather than gunicorn. `passenger_wsgi.py` in this project is the
entry point it expects.

Read the two warnings at the end before you buy anything — one of them decides
whether this will work at all.

---

## 1. What to buy

You need a plan that lists **Python hosting** or shows *Setup Python App* in
cPanel. Ordinary WordPress-only shared hosting will not run this. If the plan
page does not say Python, ask support before paying.

## 2. Upload the code

cPanel refuses to run an application directly from `public_html`, so put it in
a subfolder:

```
/home/YOURUSER/praxorax/
```

Use File Manager, or Git if you have SSH:

```bash
cd ~
git clone https://github.com/YOURNAME/YOURREPO.git praxorax
```

Do **not** upload `.env`. You will create it on the server in step 4.

## 3. Create the application

cPanel → Software → **Setup Python App** → Create Application.

| Field | Value |
|---|---|
| Python version | 3.8 or newer — the highest offered |
| Application root | `praxorax` |
| Application URL | your domain or a subdomain |
| Application startup file | `passenger_wsgi.py` |
| Application entry point | `application` |

**Use `passenger_wsgi.py`, not `app.py`.** cPanel overwrites the startup file
with its own hello-world when the application is created. Overwriting the stub
costs nothing; overwriting `app.py` would destroy the project.

Click Create. cPanel shows a command like
`source /home/YOURUSER/virtualenv/praxorax/3.11/bin/activate` — copy it, you
will need it.

## 4. Configuration

Create `/home/YOURUSER/praxorax/.env` in File Manager. Start from
`.env.example` and set at minimum:

```
DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@aws-1-eu-west-1.pooler.supabase.com:5432/postgres
SECRET_KEY=<a fresh 64-character hex string>
BASE_URL=https://yourdomain.com
SECURE_COOKIES=true
DEMO_MODE=false
UPLOAD_FOLDER=/home/YOURUSER/praxorax-uploads
```

`UPLOAD_FOLDER` points **outside** the project folder deliberately. Redeploying
would otherwise delete every file students have submitted.

Generate a new `SECRET_KEY` for production rather than reusing your development
one. Changing it signs everyone out once, which is harmless.

## 5. Install the dependencies

In the Setup Python App screen, under **Configuration files**, add
`requirements.txt` and click **Run Pip Install**.

If that fails — it sometimes does on shared hosting — use Terminal or SSH:

```bash
source /home/YOURUSER/virtualenv/praxorax/3.11/bin/activate
cd ~/praxorax
pip install -r requirements.txt
```

`psycopg2-binary` needs a prebuilt wheel for the Python version cPanel offers.
If pip tries to compile from source and fails on `pg_config`, pick a different
Python version in cPanel — that is almost always the fix.

## 6. The database

Supabase stays where it is; nothing moves. In the Supabase SQL editor run, in
order: `schema.sql`, then `migration_v3` through `migration_v8`.

If the database already has your data, run only the migrations you have not
applied yet. They are all additive and safe to re-run.

## 7. Check before trusting it

```bash
source /home/YOURUSER/virtualenv/praxorax/3.11/bin/activate
cd ~/praxorax
python preflight.py
```

It checks the Python version, the configuration, whether the database port is
actually reachable from this server, whether the upload folder is writable,
whether the mail port is open, and whether every table exists. Each failure
comes with what to do about it.

Then:

```bash
python create_admin.py
```

Restart the application in cPanel and open your domain.

---

## Two warnings

### Outbound ports may be blocked

This is the one that decides everything. Shared hosts commonly block outbound
connections on unusual ports, and your app needs two:

* **5432** to Supabase. Without it the site cannot start.
* **465 or 587** for email.

`preflight.py` tells you within seconds. If 5432 is blocked, ask support to
open it — they often will. If they refuse, Supabase's transaction pooler on
**6543** sometimes gets through. If neither works, this host cannot run this
app and no amount of configuration will change that.

Ask support *before* paying: "Does your Python hosting allow outbound TCP on
port 5432 to an external PostgreSQL server?"

### Background threads and Passenger

Email is sent on a background thread so a slow mail server never makes anyone
wait for a page. Passenger stops idle processes, which can occasionally kill a
thread mid-send. The in-app notification is already saved when that happens, so
nothing is lost but the email itself.

If you would rather be certain every message goes out, set:

```
MAIL_SYNCHRONOUS=true
```

Pages will then wait for the mail server — typically a second or two, longer if
it is slow. A fair trade on a low-traffic site; a bad one under load.

---

## Honest comparison

WhoGoHost is a reasonable choice, especially with a Nigerian client who wants
Nigerian hosting and local support in the same time zone. Files persist across
restarts, which Render's free tier does not do.

Worth knowing what else exists:

| | Cost | Trade-off |
|---|---|---|
| **WhoGoHost / GO54** | Paid | Files persist. Outbound ports are the risk. Local support. |
| **Render** | Free tier | Deploys from Git in minutes, no port problems. The free disk is wiped on every redeploy, so uploads need a paid persistent disk. |
| **Railway / Fly.io** | Small monthly | No port problems, persistent volumes, more control. Support is not in your time zone. |

If the client has already paid for WhoGoHost, use it — just run `preflight.py`
before you promise anything. If nothing has been bought yet, deploying to
Render first takes twenty minutes and tells you whether the app is ready,
separately from whether the host is.
