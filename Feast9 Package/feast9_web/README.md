# Feast9 — Patient & Case Management

A patient and case management web app built for a single-practitioner
dental practice. Runs in any browser, deployable to a cloud host so it's
reachable from any laptop.

**Stack:** Python 3 + Flask + SQLite (no external database server to manage) +
reportlab (PDFs) + openpyxl (Excel import/export). No build step — plain
server-rendered HTML/CSS/JS.

## What's included

- Patient directory (name & mobile mandatory, email optional) with search
- Treatment cases per patient, multiple active cases supported, active
  cases visually highlighted and listed above closed ones
- Standard procedure/case-type dropdown (multi-select) **plus** a free-text
  field for anything custom — manage the standard list under "Case Types"
- Doctor tagging per case; doctor list manageable (name only) plus a
  distinct color per doctor (auto-assigned, editable) used on the calendar
- **Appointment calendar** — month and day views, color-coded by doctor,
  create/edit/cancel appointments, live patient search-as-you-type, a
  "Today's Appointments" widget on the dashboard, and each patient's own
  appointment history on their detail page
- Running payment log per case with an automatically calculated pending
  balance that stays visible while the case is Active (handles overpayment
  gracefully too, e.g. if the estimate is later revised downward)
- **Signed consent forms per case** — editable consent text (auto-filled
  with patient/doctor/procedure details, edit before signing), captured
  either by signing on screen (mouse/finger/stylus) or by uploading a
  photo/scan of a paper-signed copy. A case can have more than one
  consent on file over time (e.g. a fresh one if the treatment plan
  changes materially), each kept as part of the permanent case history
  and printable as a PDF with the signature embedded
- **Tracked cost revisions** — if treatment scope changes mid-case (e.g. a
  surgery is identified after a couple of sittings), revise the estimate
  with a dated, reasoned entry instead of silently overwriting the cost;
  the balance recalculates automatically and the full history shows on the
  printed case/insurance summary
- **Visit notes** — a running, dated log on each case so you can record
  what happened at each subsequent visit without losing earlier notes
- Prescriptions per case (date, patient name/age/sex, Rx text), printable
  as a branded PDF, kept as part of the case history — automatically shows
  a prominent allergy warning if the patient has any on file
- **Medical history on patient registration** — a standard checklist
  (Diabetes, Asthma, Heart Disease, Bleeding Disorders, etc.), pregnancy/
  nursing status for female patients, a standard drug-allergy checklist
  plus free text for anything else, and an emergency contact (name,
  relation, number). Shown prominently on the patient's page and included
  on printed summaries
- Dashboard: overdue & due-today follow-ups, total outstanding payments
- Printable PDF summaries per patient or per case (a dedicated "insurance"
  version includes procedures performed and full cost breakdown)
- Reports: revenue collected, cases closed, new cases/patients, for any
  date range, plus a monthly chart — exportable as PDF or CSV
- One-time historic data import from Excel (template provided, tolerant of
  common header spelling variants, handles thousands of rows in one go)
- Username/password login (single practitioner account, created on first
  run), with **self-service password recovery** via a security question
  (no email server needed) plus an emergency CLI script as a last resort
- **Configurable branding** — upload your own clinic logo from Settings
  (used in the nav bar, login screen, and every printed PDF); the login
  page also carries a scripture verse and a small inset image of Saint
  Apollonia, the patron saint of dentistry
- **Backups** — automatic daily snapshots (zero setup) plus a one-click
  "Download Backup Now" for keeping an off-server copy
- **Security hardening** — CSRF protection on every form, rate-limited
  login/password-recovery attempts, and standard security response headers
  (see Section 7 for the full picture of what's covered and what's still
  on you, like enabling HTTPS)

---

## 1. Run it locally (test drive before deploying)

Requires Python 3.10+. Check your version first:

- **Windows (PowerShell):** `python --version` (if that's not found, try `py --version`)
- **Mac/Linux:** `python3 --version`

If you don't have Python yet, get it from https://www.python.org/downloads/
(on Windows, tick **"Add python.exe to PATH"** during install).

### Windows (PowerShell)

```powershell
cd feast9_web
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

If `Activate.ps1` is blocked with a message about execution policies, run
this once (in the same PowerShell window) and then try activating again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

You'll know the virtual environment is active because your prompt changes
to start with `(venv)`. From then on `python` and `pip` inside this window
refer to the project's own isolated copies.

### Mac / Linux

```bash
cd feast9_web
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Either way, once `python run.py` is running

You'll see output ending in something like:
```
 * Running on http://127.0.0.1:5000
```
Open **http://127.0.0.1:5000** in your browser. The first visit takes you
to a one-time setup screen to create your admin username/password — pick
anything, this is just for your own local test. After that you'll land on
the login screen on every visit.

Leave that PowerShell/Terminal window open — closing it stops the server.
To stop it on purpose, click into that window and press `Ctrl+C`.

### See it with sample data already filled in

A brand-new install starts completely empty, so the dashboard looks bare.
To populate it with a few sample patients, doctors, cases, payments, and a
prescription so you can see what everything looks like in action:

1. Complete the one-time setup screen and log in (above) first.
2. Open a **second** PowerShell/Terminal window (keep the server running in
   the first one), `cd` into `feast9_web` again, activate the venv
   the same way, then run:
   ```
   python seed_demo_data.py
   ```
3. Refresh the app in your browser — the dashboard, patient list, and
   reports will now show real-looking data you can click through.

This step is optional and only for trying things out — skip it (or delete
the `instance` folder to wipe it before going live) when you're ready to
enter real patients.

Your data is stored in `instance/feast9.db` next to the app.
Delete that whole `instance` folder any time to start completely fresh
(e.g. right before doing your real historic data import).

---

## 2. Deploying to the cloud

The app is a standard Flask app shipped with a `Dockerfile`, so it runs on
any host that accepts a container — or directly with Python on a VPS. Pick
whichever you're most comfortable with.

> **Important — persistent storage.** This app stores everything in one
> SQLite file. Most cloud hosts wipe the container's local disk on every
> redeploy/restart unless you attach a **persistent disk/volume**. Always
> mount one at the path given by the `DATA_DIR` environment variable
> (defaults to `/data` in the Docker image). The instructions below call
> this out for each host.

### Option A — Render.com (easiest, has a free tier)

1. Push this folder to a GitHub repository.
2. In Render: **New → Blueprint**, point it at your repo. Render reads
   `render.yaml` automatically and provisions:
   - a web service running the included `Dockerfile`
   - a 1 GB **persistent disk** mounted at `/data` (this is what makes your
     data survive redeploys — don't skip it)
   - a random `SECRET_KEY`
3. Deploy. Render gives you a `https://master-dentizt.onrender.com`-style
   URL — open it, complete the one-time setup screen, and you're live.
4. (Optional) Add a custom domain under the service's **Settings → Custom
   Domains**.

If you'd rather click through the UI instead of using the blueprint: create
a **Web Service** from your repo, runtime **Docker**, then under
**Disks** add one sized 1 GB+ mounted at `/data`, and under
**Environment** add `SECRET_KEY` (any long random string) and
`SESSION_COOKIE_SECURE=1`.

### Option B — Railway.app

1. Push to GitHub, then in Railway: **New Project → Deploy from GitHub repo**.
   Railway detects the `Dockerfile` automatically.
2. Add a **Volume** (Railway's persistent disk) mounted at `/data`.
3. Under **Variables**, add `SECRET_KEY` and `SESSION_COOKIE_SECURE=1`,
   and `DATA_DIR=/data` if it isn't already picked up from the Dockerfile.
4. Deploy and open the generated URL.

### Option C — Your own VPS (DigitalOcean, AWS Lightsail, Hetzner, etc.) with Docker

This gives you full control and is the cheapest long-term option (a $5-6/mo
VPS is plenty for a single practice).

```bash
# On the server, with Docker + Docker Compose installed:
git clone <your-repo-url> feast9
cd feast9

cp .env.example .env
# edit .env: set a real SECRET_KEY, and SESSION_COOKIE_SECURE=1 once you
# have HTTPS set up (see below)

export $(grep -v '^#' .env | xargs)   # or use `docker compose --env-file .env`
docker compose up -d --build
```

The app is now listening on port 8000. Put a reverse proxy in front of it
for HTTPS — the easiest path is **Caddy** (automatic HTTPS via Let's
Encrypt, one config file):

```
# /etc/caddy/Caddyfile
your-domain.com {
    reverse_proxy localhost:8000
}
```

or **nginx** with certbot if you already run nginx. Either way, once HTTPS
is live, set `SESSION_COOKIE_SECURE=1` in `.env` and restart
(`docker compose up -d`) so login cookies are sent securely.

Your data lives in the `feast9_data` Docker volume — back it up
periodically with the included helper:

```bash
./backup.sh        # writes feast9_backup_<timestamp>.tar.gz
```

### Option D — Plain Python on a VPS (no Docker)

```bash
sudo apt update && sudo apt install -y python3-venv
git clone <your-repo-url> feast9 && cd feast9
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
export DATA_DIR=/var/lib/feast9
export SESSION_COOKIE_SECURE=1   # once HTTPS is set up
sudo mkdir -p $DATA_DIR && sudo chown $USER $DATA_DIR

gunicorn -w 2 -k gthread --threads 4 -b 127.0.0.1:8000 --timeout 120 wsgi:app
```

Run that under `systemd` or `supervisor` so it restarts on reboot/crash,
and put nginx/Caddy in front of it for HTTPS, same as Option C.

---

## 3. First login & one-time setup checklist

1. Open your deployed URL → you'll land on **Set up admin account**. Choose
   a username and password, and a security question/answer (this is what
   lets you self-recover your password later — there's no email server
   involved, see "Password recovery" below).
2. Go to **Settings** and fill in your clinic address/phone — these appear
   on every printed prescription and summary. While you're there, upload
   your real logo if you'd rather not use the bundled placeholder.
3. Go to **Doctors** and add yourself (and any associate dentists).
4. Go to **Case Types** to review/edit the standard procedure list — add
   anything specific to your practice.
5. Go to **Import Data** to bring in your existing ~8,000 patient records:
   - Download the template, fill it in (or remap your existing spreadsheet's
     headers — the importer recognizes common variants like "Contact
     Number" or "Gender", and will even carry over free-text "Medical
     History"/"Allergies" columns if your old sheet has them).
   - Upload it. You'll see a preview with a count of valid rows and a list
     of any rows that would be skipped (with the reason) before anything
     is saved — nothing is written until you click **Confirm Import**.
6. Start adding cases against patients day to day from here on.

---

## 4. Day-to-day notes

- **Mobile + name are mandatory** on every patient; email is optional —
  enforced both in the UI and on the server.
- A patient can have **any number of Active cases at once**; closed cases
  drop to the bottom of their list and stop counting toward the
  dashboard's outstanding-balance total.
- **Pending balance** on a case = Total Cost − sum of logged payments. It's
  shown and counted on the dashboard only while the case is Active; once
  you close a case, that case's balance no longer affects the dashboard
  total (per the original spec).
- **Prescriptions** are scoped to a case and stay in that case's history
  permanently — print any past prescription again any time.
- **Case summary PDF** comes in two flavors from the same button group:
  a plain "Print Summary" and an "Insurance Copy" that's phrased for
  claims (procedures performed + full cost breakdown).
- **Medical history / allergies** entered on a patient's record surface
  automatically: a red alert chip on their page, an allergy banner on
  every case of theirs, and a bold allergy warning on every prescription
  PDF for that patient — so it's hard to miss before prescribing.
- **Consent forms**: a case shows "⚠ No consent yet" next to its status
  until at least one is on file, then switches to "✓ Consent on file".
  Sign on a tablet/laptop right at the chair, or print a blank copy first
  (Case page → Consent Forms → "Print a blank consent form") for a
  paper-and-pen signature, then come back and upload the scanned/
  photographed copy — either way it's saved permanently against the case.
- **Password recovery** has two layers: (1) the "Forgot password?" link on
  the login page asks your security question and lets you set a new
  password yourself, no email needed; (2) if you also forget the answer
  to that, run `python reset_admin_password.py` directly on your server
  (same access you used to deploy the app) — it resets the password
  without needing to log in at all. You can change your security question
  any time from Settings.
- **Backups** happen automatically once a day, but make a habit of using
  **Settings → Download Backup Now** every so often and saving that file
  somewhere off the server — see Section 8.

---

## 5. Updating the app later

```bash
git pull
docker compose up -d --build      # Docker route
# or, plain Python route:
git pull && source venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart master-dentizt   # if running under systemd
```

The SQLite schema is additive-safe across the versions in this package —
`init_db()` runs `CREATE TABLE IF NOT EXISTS` on every boot, so pulling
updates never touches your existing data. If you're updating from a
version before the Appointments module existed, the app automatically
adds the new `color` column to your existing doctors on first boot and
assigns each one a distinct color — no manual steps needed.

---

## 6. Project layout

```
feast9_web/
├── app/
│   ├── __init__.py        Flask app factory
│   ├── config.py          paths, theme colors, secret key handling
│   ├── constants.py       dropdown lists, default procedure seed list
│   ├── validators.py      mandatory-field & format validation
│   ├── db.py               all SQLite schema + queries
│   ├── auth.py             password hashing, login_required decorator
│   ├── csrf.py              CSRF token generation + validation
│   ├── backup.py             on-demand + automatic daily DB snapshots
│   ├── branding.py         custom logo upload/storage/resolution
│   ├── excel_import.py     historic-data importer
│   ├── pdf_reports.py      prescription/case/patient/report PDFs
│   ├── routes/             one blueprint per feature area
│   ├── templates/          Jinja2 HTML templates
│   └── static/             CSS, JS, default logo, Saint Apollonia art
├── requirements.txt
├── run.py                  local dev entry point
├── wsgi.py                 production entry point (gunicorn)
├── seed_demo_data.py       optional: fills the app with sample data
├── reset_admin_password.py emergency CLI password reset
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── backup.sh
└── .env.example
```

---

## 7. Security notes

What's actually protected:

- **Passwords & security answers** are hashed with Werkzeug's
  `generate_password_hash` (PBKDF2) — never stored in plain text.
- **SQL injection**: every query uses parameterized statements, nowhere
  builds SQL from raw user input.
- **XSS**: Jinja2 autoescapes everything by default and the codebase
  never opts out of that (no `|safe` filters on user-controlled data).
- **CSRF**: every form that changes data carries a per-session token that's
  verified on submit, so another site can't quietly submit actions using
  your logged-in session.
- **Brute-force login/password-recovery attempts** are rate-limited
  (8 failed attempts per 15 minutes per IP, tracked in the database so it
  holds up across multiple worker processes and survives restarts).
- **Security headers** (`X-Frame-Options`, `X-Content-Type-Options`,
  a `Content-Security-Policy`, `Referrer-Policy`) are set on every
  response.
- The app **warns in the server log** on startup if you're still running
  with the default placeholder `SECRET_KEY`.

What's still on you to get right:

- **Set `SESSION_COOKIE_SECURE=1` once you're on HTTPS** (every host in
  this guide supports HTTPS) — without it, login cookies can be sent
  unencrypted. This is the single most important step after deploying.
- **Use a real, random `SECRET_KEY`** in production (see `.env.example`)
  — generate one with `python3 -c "import secrets;print(secrets.token_hex(32))"`.
- **The data at rest is not encrypted.** The SQLite file (which now
  includes medical history) is plain, readable data on disk. If your host
  offers encrypted disks/volumes (most do, often on by default for managed
  platforms), use them. This matters more here than on a typical app
  because of the patient medical/allergy data this app stores — treat
  server access and backup files with the same care you'd give a paper
  patient file.
- **Security questions are inherently weaker than passwords** — they're
  the trade-off made to avoid needing an email server. Pick a question
  whose answer isn't easily guessed or publicly known about you.
- This is still a single-practitioner tool without an audit log of who
  changed what (there's only one login, so this matters less) and without
  automatic dependency-vulnerability scanning — keep `pip install -r
  requirements.txt --upgrade` in mind periodically.

## 8. Backups

Two layers, both described in the app's **Settings → Backups** panel:

- **Automatic** — the app snapshots the database once per day on its own
  (the first request of a new calendar day triggers it), keeping the last
  14 daily snapshots and pruning older ones automatically. Zero setup,
  zero ongoing cost — no cron job or separate service needed.
- **Manual / on-demand SQLite backup** — click **Download Backup Now** any
  time to get an immediate copy streamed straight to your browser. This is
  the full restore point — everything in one file.
- **Excel "Plan B" export** — click **Export to Excel** to get a
  colour-coded spreadsheet with one row per case, containing patient name,
  contact, age, sex, medical conditions, allergies, emergency contact,
  case title, status, doctor, procedures, costs and balance, and follow-up
  date. Active cases are green, overdue follow-ups are red, due-today are
  amber, closed cases are white. This file is readable on any laptop,
  tablet, or phone without needing the app or network at all — genuine
  Plan B if the system is unavailable.

**The automatic snapshots alone are not a real backup strategy** — they
live on the same disk as your live database, so if that disk or the whole
server is lost, the snapshots go with it. Periodically use **Download
Backup Now** and save the file somewhere genuinely separate: your laptop,
a cloud storage folder, emailed to yourself, anywhere off that server.
Treat this the same way you'd think about backing up any patient record
system — the cost of doing it is one click; the cost of not having one
when you need it is much higher.

To restore from a backup: stop the app, replace the live database file
(`instance/feast9.db`, or wherever your `DATA_DIR` points) with
the backup file, and start the app again. Do this with the app stopped to
avoid a half-written file.

## 9. Branding — logo, login verse, and Saint Apollonia image

The easiest way to set your real clinic logo is **Settings → Clinic
Logo** — upload a PNG/JPG (up to 5 MB, auto-resized) and it immediately
appears in the top bar, the login screen, and every printed PDF, with no
file editing or redeploy needed. Use "Remove Custom Logo" there to revert
to the bundled placeholder.

If you'd rather replace the bundled default directly instead of using the
upload, swap out `app/static/img/logo.png` and `app/static/img/favicon.png`
(same filenames, square images work best).

The login page also carries a short scripture verse (Jeremiah 30:17) and
a small framed inset image of Saint Apollonia, the patron saint of
dentistry, captioned "St Apollonia — pray for us."
(`app/static/img/saint_apollonia.png`) — edit
`app/templates/login.html` directly if you'd like to change or remove
either.
