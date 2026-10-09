# NoteShare

## 1. Project overview

NoteShare is a peer-to-peer notes marketplace for college students: students upload their
academic notes, find notes for their subjects, rate them, and report inappropriate content
to moderators.

The application is built with Flask and MySQL and is being developed in phases. This
repository currently contains:

- **Phase 1: the project foundation and database layer** (sections 2–22)
- **Phase 2: authentication and roles** ([section 23](#23-phase-2-authentication-and-roles))
- **Phase 3: core note features** — upload, browse/search/filter, details, download, My
  Notes, delete — plus search-engine and sharing support ([section 24](#24-phase-3-core-note-features))
- **Phase 4: ratings, reports, moderation and subjects** ([section 25](#25-phase-4-ratings-reports-moderation-and-subjects))

## 2. Phase 1 scope

Implemented in this phase:

- Project structure, dependency list and environment-based configuration (`config.py`)
- A minimal Flask application factory (`app.py`) — Phase 2 added the routes
- SQLAlchemy models for `users`, `subjects`, `notes`, `ratings` and `reports` (`models.py`)
- The equivalent raw MySQL DDL for documentation and manual setup (`schema.sql`)
- An idempotent seed script that creates missing tables, 5 test users and 6 subjects (`seed.py`)

Not implemented yet: see [section 22](#22-current-limitations-and-future-phases).

## 3. Technology stack

| Concern           | Choice                                                    |
| ----------------- | --------------------------------------------------------- |
| Language          | Python 3.11+ (tested with 3.14)                           |
| Web framework     | Flask 3.1                                                 |
| ORM               | Flask-SQLAlchemy 3.1 on SQLAlchemy 2.0                    |
| Database          | MySQL 8.0 (8.0.16 or newer; tested with 8.0.46)           |
| MySQL driver      | PyMySQL (with `cryptography` for MySQL 8 authentication)  |
| Configuration     | python-dotenv                                             |
| Password hashing  | Werkzeug (`generate_password_hash`, scrypt)               |
| Templates         | Jinja2, plain HTML and CSS, a little vanilla JavaScript   |
| CSRF protection   | Flask-WTF (`CSRFProtect`)                                 |
| Tests             | pytest, against a separate MySQL test database            |

## 4. Project structure

```
NoteShare/
├── app.py                # Application factory, CSRF, error pages, dev entry point
├── auth.py               # Register/login/logout routes, decorators, current user
├── notes.py              # Browse, upload, details, ratings, reports, download, My Notes, delete
├── moderation.py         # Moderation dashboard and dismiss/remove/warn/ban actions
├── admin.py              # Subject administration (admins only)
├── seo.py                # robots.txt, sitemap.xml, llms.txt, favicon.ico, absolute URLs
├── migrate.py            # Safe, repeatable schema upgrades (e.g. reports.details)
├── config.py             # Loads .env, defines Config, validates required settings
├── models.py             # db = SQLAlchemy(), the five models, role hierarchy
├── schema.sql            # Raw MySQL DDL matching models.py
├── seed.py               # Creates missing tables and inserts seed users/subjects
├── requirements.txt      # Runtime dependencies
├── requirements-dev.txt  # Runtime + test dependencies (pytest)
├── pytest.ini
├── .env.example          # Template for your local .env (no real secrets)
├── .gitignore
├── templates/
│   ├── base.html         # Layout: head/SEO tags, header, navigation, flash messages, footer
│   ├── _forms.html       # Form field macro (label, input, inline error)
│   ├── _notes.html       # Note card, ratings, status label and pagination macros
│   ├── _layout.html      # Breadcrumb macro
│   ├── home.html         # Browse/search page (the homepage)
│   ├── upload.html
│   ├── note_detail.html
│   ├── my_notes.html
│   ├── moderation.html   # Open reports grouped by note
│   ├── admin_subjects.html
│   ├── admin_subject_form.html
│   ├── register.html
│   ├── login.html
│   ├── account.html      # Your account details
│   ├── error.html        # 400/403/404/405/413/500 pages
│   ├── sitemap.xml       # Rendered by /sitemap.xml
│   └── llms.txt          # Rendered by /llms.txt
├── static/
│   ├── css/style.css
│   ├── js/main.js        # Optional: flash dismiss buttons, file-size warning
│   ├── favicon.svg, favicon.ico, apple-touch-icon.png
│   └── og-image.png      # 1200x630 social share image
├── tests/
│   ├── conftest.py       # Test app, test-database guard, fixtures, test files
│   ├── test_auth.py      # Phase 2
│   ├── test_notes.py     # Phase 3
│   ├── test_seo.py       # Titles, headings, canonical/robots, sitemap, structured data
│   └── test_phase4.py    # Ratings, reports, flagging, moderation, subjects, end-to-end
└── uploads/              # Uploaded note files (UUID names); contents are git-ignored
```

`uploads/.gitkeep` is an empty placeholder so Git keeps the folder.

Import direction (no circular imports): `app.py → auth.py, notes.py, seo.py, config.py,
models.py, moderation.py, admin.py`; `moderation.py → auth.py, notes.py, models.py`;
`notes.py, admin.py → auth.py, models.py`; `auth.py, seo.py → models.py`;
`seed.py → app.py, models.py`.

## 5. Prerequisites

- Windows 10/11 with VS Code (Linux/macOS commands are given where they differ)
- Python 3.11 or newer — check with `py --version` (Windows) or `python3 --version`
- MySQL Community Server 8.0.16 or newer, **or** Docker Desktop (see 6b)
- Git (optional, for version control)

> **XAMPP users:** XAMPP ships **MariaDB**, not MySQL. NoteShare's schema uses MySQL 8
> features (expression defaults, enforced CHECK constraints, the `utf8mb4_0900_ai_ci`
> collation), so use MySQL 8 instead. If XAMPP's database is running on port 3306, stop
> it first or MySQL will not be able to use that port.

## 6. Installing MySQL

### 6a. MySQL Community Server (native install)

**Windows:** download the *MySQL Installer for Windows* from
<https://dev.mysql.com/downloads/installer/> and choose **MySQL Server 8.0** (and optionally
**MySQL Workbench**). During setup, keep the default port 3306, keep *Use Strong Password
Encryption*, set a root password you will remember, and let it install the Windows service.

Alternatively, from PowerShell: `winget install Oracle.MySQL`

**macOS:** `brew install mysql@8.0`  **Ubuntu/Debian:** `sudo apt install mysql-server`

### 6b. Docker alternative

If Docker Desktop is installed, this runs MySQL 8.0 on `localhost:3306` only, with data
kept in a named volume:

```powershell
docker run -d --name noteshare-mysql -p 127.0.0.1:3306:3306 `
  -e MYSQL_ROOT_PASSWORD=<choose-a-root-password> `
  -v noteshare-mysql-data:/var/lib/mysql mysql:8.0 --character-set-server=utf8mb4
```

(On Linux/macOS replace the backticks with `\`.)

## 7. Starting the MySQL server

| Platform               | Command                                                        |
| ---------------------- | -------------------------------------------------------------- |
| Windows (service)      | `Start-Service MySQL80` in an **administrator** PowerShell, or *Services* → *MySQL80* → Start |
| macOS (Homebrew)       | `brew services start mysql@8.0`                                |
| Linux                  | `sudo systemctl start mysql`                                   |
| Docker                 | `docker start noteshare-mysql`                                 |

Connect as root to run the setup statements below, using either:

- **Command line:** `mysql -u root -p` (Windows: run it from *MySQL 8.0 Command Line Client*,
  or add `C:\Program Files\MySQL\MySQL Server 8.0\bin` to `PATH`).
  Docker: `docker exec -it noteshare-mysql mysql -u root -p`
- **MySQL Workbench:** open the *Local instance MySQL80* connection and use a query tab.

## 8. Creating the database

The database must exist **before** `seed.py` runs (the seed script creates tables, not the
database itself):

```sql
CREATE DATABASE IF NOT EXISTS noteshare
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

## 9. Creating a dedicated MySQL user

Do not run the application as `root`. Create a dedicated account, replacing the placeholder
with a strong password of your own:

```sql
-- Native install (the app connects from the same machine):
CREATE USER 'noteshare_user'@'localhost' IDENTIFIED BY '<YOUR_APP_DB_PASSWORD>';
```

With Docker, connections from Windows arrive through Docker's network rather than as
`localhost`, so create the user for any host instead (the container only listens on
`127.0.0.1`, so it is still not reachable from other machines):

```sql
CREATE USER 'noteshare_user'@'%' IDENTIFIED BY '<YOUR_APP_DB_PASSWORD>';
```

## 10. Granting the required database permissions

Grant only what the application needs on the `noteshare` database (use `'%'` instead of
`'localhost'` if you created the user that way):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON noteshare.* TO 'noteshare_user'@'localhost';
SHOW GRANTS FOR 'noteshare_user'@'localhost';
```

`CREATE`, `INDEX` and `REFERENCES` are needed for `seed.py` to create tables and foreign
keys; `ALTER` is for future schema changes. The account deliberately has no `DROP` privilege
and no access to other databases.

## 11. Creating and activating a Python virtual environment

Open the project folder in VS Code and use its terminal (`` Ctrl+` ``).

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script, allow local scripts once for your user:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`. In VS Code, also pick this interpreter via
*Python: Select Interpreter* → `.venv`.

## 12. Installing Python dependencies

With the virtual environment active:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

To also run the automated tests, install `requirements-dev.txt` instead (it includes
`requirements.txt` plus pytest):

```powershell
python -m pip install -r requirements-dev.txt
```

## 13. Creating the .env file from .env.example

**Windows:** `Copy-Item .env.example .env`  **Linux/macOS:** `cp .env.example .env`

Then edit `.env`:

```dotenv
DATABASE_URL=mysql+pymysql://noteshare_user:<YOUR_APP_DB_PASSWORD>@localhost:3306/noteshare
SECRET_KEY=<paste a generated key here>
UPLOAD_FOLDER=uploads
SESSION_COOKIE_SECURE=false
SITE_URL=
TEST_DATABASE_URL=mysql+pymysql://noteshare_user:<YOUR_APP_DB_PASSWORD>@localhost:3306/noteshare_test
```

`SESSION_COOKIE_SECURE` must be `true` in production behind HTTPS, and `false` for local
`http://` development (otherwise the browser drops the session cookie and logins don't stick).
`SITE_URL` is the site's public address once it has a domain (e.g.
`https://notes.example.edu`); leave it empty locally (see section 24.8).
`TEST_DATABASE_URL` is only used by the tests (see [section 23.9](#239-running-the-tests)).

Generate the secret key with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

`.env` is listed in `.gitignore`. **Never commit it.** Only `.env.example` belongs in Git.

The application refuses to start (with an explanation) if `DATABASE_URL` or `SECRET_KEY` is
missing, still contains the example placeholder, if the secret key is shorter than 32
characters, or if the URL is not a `mysql+pymysql://` URL. It never falls back to SQLite.

`UPLOAD_FOLDER` may be relative; it is resolved against the project folder, not the
terminal's current directory.

## 14. Configuring DATABASE_URL correctly

Format: `mysql+pymysql://<user>:<password>@<host>:<port>/<database>`

Characters that have a meaning in URLs must be **percent-encoded** inside the password:

| Character | `@`   | `:`   | `#`   | `/`   | `%`   | `?`   |
| --------- | ----- | ----- | ----- | ----- | ----- | ----- |
| Encoded   | `%40` | `%3A` | `%23` | `%2F` | `%25` | `%3F` |

Encode a password safely with:

```powershell
python -c "from urllib.parse import quote; print(quote(input('password: '), safe=''))"
```

Example: the password `p@ss#1` becomes `p%40ss%231`.

## 15. Initializing tables using seed.py

```powershell
python seed.py
```

This:

1. validates the configuration and connects to MySQL,
2. creates any of the five tables that do not exist yet (existing tables are left alone),
3. inserts the 5 test users and 6 subjects that are missing (looked up by email / subject code),
4. commits — or rolls back everything if any step fails,
5. re-reads the seed records to verify them, and prints the development credentials.

It is safe to run repeatedly: a second run reports `0 created this run`. It never drops
tables, deletes rows, or modifies existing rows (including seed accounts whose password you
changed). Expected output:

```
NoteShare database initialization
==============================================================================
Database connection: successful (MySQL server 8.0.x)
Tables: created/verified (users, subjects, notes, ratings, reports)
Users: 5 verified (5 created this run)
Subjects: 6 verified (6 created this run)
...
```

`schema.sql` contains the same tables as raw MySQL DDL. You do not need it when you use
`seed.py`; it is there for documentation and for creating the tables by hand
(`USE noteshare; SOURCE schema.sql;`). It only uses `CREATE TABLE IF NOT EXISTS`.

## 16. Verifying the database tables

```sql
USE noteshare;
SHOW TABLES;            -- notes, ratings, reports, subjects, users
SHOW CREATE TABLE ratings;
```

To list every named constraint:

```sql
SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = 'noteshare'
ORDER BY TABLE_NAME, CONSTRAINT_TYPE;
```

## 17. Checking seeded users and subjects

```sql
SELECT id, name, email, role, branch, year, warnings, is_banned, created_at
FROM users ORDER BY id;                                  -- 5 rows

SELECT role, COUNT(*) FROM users GROUP BY role;          -- admin 1, moderator 1, student 3

SELECT code, name, semester FROM subjects ORDER BY code; -- 6 rows

SELECT semester, COUNT(*) FROM subjects GROUP BY semester; -- 5 → 3, 6 → 3
```

There is no need to look at `password_hash` values; they are one-way hashes.

## 18. Running the Flask application

```powershell
python app.py
```

or, with auto-reload and the interactive debugger, `flask --app app run --debug`. The server
starts on <http://127.0.0.1:5000>, which shows the browse page. Creating the app does
not open a database connection; the first request does.

Flask's built-in server is for development only. Never use it, or `--debug`, in production;
deploy behind a production WSGI server (e.g. Gunicorn or Waitress) in a later phase.

## 19. Development login credentials

`seed.py` creates these accounts. Log in with them at <http://127.0.0.1:5000/login>.

| Role      | Email                             | Password           |
| --------- | --------------------------------- | ------------------ |
| Admin     | `admin@noteshare.example.com`     | `AdminDev#2026`    |
| Moderator | `moderator@noteshare.example.com` | `ModDev#2026`      |
| Student 1 | `student1@noteshare.example.com`  | `Student1Dev#2026` |
| Student 2 | `student2@noteshare.example.com`  | `Student2Dev#2026` |
| Student 3 | `student3@noteshare.example.com`  | `Student3Dev#2026` |

**These are for local development only.** They are published in this repository, so never
create them on a server that anyone else can reach, and never reuse them anywhere.

## 20. Troubleshooting

| Message                                                           | Cause and fix |
| ----------------------------------------------------------------- | ------------- |
| `Configuration error: ... DATABASE_URL is not set`                | `.env` is missing or in the wrong folder. It must sit next to `config.py`. |
| `... still contains the placeholder password 'CHANGE_ME'`         | You copied `.env.example` without editing it. |
| `Database error (2003): Can't connect to MySQL server`            | MySQL is not running or the host/port is wrong. Start it (section 7). |
| `Database error (1045): Access denied for user`                   | Wrong user/password, an un-encoded special character in the password (section 14), or — with Docker — the user was created for `'localhost'` instead of `'%'`. |
| `Database error (1049): Unknown database 'noteshare'`             | Create the database first (section 8). |
| `Database error (1044)` / `(1142) ... command denied`             | Run the `GRANT` statement (section 10) for the exact user and host. |
| `RuntimeError: 'cryptography' package is required`                | Re-run `pip install -r requirements.txt` inside the virtual environment. |
| `ModuleNotFoundError: No module named 'flask'`                    | The virtual environment is not active (section 11). |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| MySQL won't start / port 3306 in use                              | Another server (often XAMPP's MariaDB) is using port 3306. Stop it. |
| Syntax error near `(UTC_TIMESTAMP())` or `CHECK`                  | Your server is older than MySQL 8.0.16, or is MariaDB. Use MySQL 8.0.16+. |

## 21. Security notes

- Secrets live only in `.env`, which is git-ignored. The app refuses to start with a
  missing, placeholder or short `SECRET_KEY`.
- Passwords are stored only as Werkzeug scrypt hashes (`password_hash`), never in plain text.
- The application uses a dedicated MySQL account with privileges on `noteshare` only.
- Error messages from `seed.py` show MySQL's error, which never includes the password, and
  never print the database URL or the secret key.
- Uploaded files will be stored on disk under `uploads/` (git-ignored), never inside the
  database. Only `pdf, docx, pptx, jpg, png` are configured as allowed, and requests are
  capped at 10 MiB (`MAX_CONTENT_LENGTH`).

### Database design decisions

- **Integrity is enforced by MySQL**, not just Python: unique keys (`users.email`,
  `subjects.code`, `ratings(note_id, student_id)`, `reports(note_id, reporter_id)`),
  foreign keys, `ENUM` columns for role/status values, and `CHECK` constraints (stars 1–5,
  non-negative counters). Constraints have explicit names (`uq_`, `fk_`, `ck_`, `ix_`), so
  errors say which rule was broken.
- **Deletion policy:** users are not meant to be deleted — ban them with `is_banned`.
  Foreign keys to `users` and `subjects` are `ON DELETE RESTRICT`, so MySQL refuses to
  delete a user or subject that still has notes, ratings or reports. Notes are normally
  hidden with `status = 'removed'`; if a note row is deleted, its ratings and reports are
  deleted with it (`ON DELETE CASCADE`).
- **Timestamps** are stored in UTC. MySQL's `DATETIME` has no time zone, so the column
  default is `UTC_TIMESTAMP()` and the models return timezone-aware (UTC) Python
  datetimes. Convert to local time only when displaying.
- **`Note.update_avg_rating()`** recalculates `avg_rating` with a SQL `AVG()` over the
  note's ratings (rounded to 2 decimals, 0 when there are none) and returns the value. It
  **does not commit**: call `db.session.commit()` afterwards, in the same transaction as the
  rating change.
- `avg_rating` is a `DOUBLE`, because MySQL's `FLOAT` is single-precision.
- Role and status enums rely on MySQL's strict SQL mode (the default in MySQL 8) to reject
  invalid values; the models also reject them in Python before they reach the database.

## 22. Current limitations and future phases

Phase 1 contained no pages or routes. Phase 2 added accounts (section 23), Phase 3 the
note features (section 24) and Phase 4 ratings, reports, moderation and subject
administration (section 25).

Schema changes after Phase 1 are applied by `migrate.py` (section 25.8), which only adds
columns and is safe to run repeatedly. If the schema starts changing often, switch to a
full migration tool such as Flask-Migrate.

## 23. Phase 2: Authentication and Roles

Phase 2 adds accounts, sign-in and role-based access control. The code lives in `auth.py`
(a Flask blueprint); `app.py` registers it. No database schema change was needed: Phase 2
uses the existing `users` table as it is.

### 23.1 Routes

| Route       | Method    | Access              | Purpose |
| ----------- | --------- | ------------------- | ------- |
| `/`         | GET       | anyone              | The browse page (Phase 3, section 24) |
| `/register` | GET, POST | signed-out visitors | Create a student account |
| `/login`    | GET, POST | signed-out visitors | Sign in |
| `/logout`   | POST only | anyone              | Sign out |
| `/account`  | GET       | signed-in users     | Your account details |

After signing in, users land on the browse page (`/`), or on the page they originally
asked for. Signed-in users who open `/login` or `/register` are sent to `/`.

### 23.2 Registration

The form asks for full name, college email, password, branch and year (1–6, matching the
`ck_users_year_range` check in MySQL). The server validates every field, whatever the
browser did:

- Name and branch are required, trimmed (repeated spaces collapsed) and limited to 100 characters.
- Email is trimmed and lower-cased, must look like `name@domain.tld`, and must not already
  be registered. The check is backed by MySQL's `uq_users_email` unique key, so two
  simultaneous sign-ups with one email cannot both succeed.
- The password must be 8–128 characters.

On errors the form is shown again with a message under each wrong field; name, email,
branch and year are kept, and the password field is always left empty. On success the
user is redirected to `/login` with *"Registration successful! You can now log in."*

No particular college email domain is enforced, because none has been specified. If one is
needed later, add it as a setting in `config.py` rather than hard-coding it.

**Public registration only ever creates students.** The role is set to `student` on the
server; `role`, `warnings`, `is_banned` or any other extra fields in the submitted form are
ignored.

### 23.3 Creating moderators and administrators

Moderator and admin accounts are never created through the website:

- **Development:** `python seed.py` creates one admin and one moderator (section 19).
- **Otherwise:** a database administrator promotes an existing account directly in MySQL:

  ```sql
  UPDATE users SET role = 'moderator' WHERE email = 'person@college.example';
  ```

The change applies on that user's next request; they do not need to sign in again.

### 23.4 Login, sessions and logout

- Passwords are hashed with Werkzeug's `generate_password_hash` (scrypt) and checked with
  `check_password_hash`. Plain-text passwords are never stored, logged or put in the session.
- A wrong password and an unknown email both give the same message, *"Invalid email or
  password."*, and take about the same time, so the form does not reveal which emails have
  accounts. The email is kept in the form; the password is not.
- After a successful login the old session is cleared and only `session["user_id"]` is
  stored. The signed session cookie is `HttpOnly` and `SameSite=Lax`, and `Secure` when
  `SESSION_COOKIE_SECURE=true`.
- On every request, `get_current_user()` loads the user from MySQL by that ID. Name, role
  and ban status always come from the database, never from the cookie. If the user has been
  deleted, the session is cleared.
- After login the user goes to the `next` page they originally asked for, but only if it
  is a path on this site; anything else (`https://…`, `//…`, `/\…`, auth pages) is ignored
  and the user goes to `/account`.
- Logout is a POST form (the "Log out" button in the header) with a CSRF token. It clears
  the session and shows *"You have been logged out successfully."*

### 23.5 Banned users

- A banned user who enters the correct password is not signed in and sees *"Your account
  has been suspended."*
- A user who is banned while signed in loses access on their next request: the session is
  cleared and they are sent to `/login` with the same message.

Until the moderation tools exist, ban an account in MySQL with
`UPDATE users SET is_banned = TRUE WHERE email = '…';`.

### 23.6 Roles and decorators

Roles form a hierarchy, defined once in `models.ROLE_LEVELS`:

| Role      | Student routes | Moderator routes | Admin routes |
| --------- | :------------: | :--------------: | :----------: |
| student   | yes            | no               | no           |
| moderator | yes            | yes              | no           |
| admin     | yes            | yes              | yes          |

Use the decorators from `auth.py` on future routes:

```python
from auth import login_required, role_required

@bp.route("/notes/upload")
@login_required                 # any signed-in, non-banned user
def upload(): ...

@bp.route("/reports")
@role_required("moderator")     # moderators and admins
def reports(): ...

@bp.route("/subjects")
@role_required("admin")         # admins only
def subjects(): ...
```

`role_required` already includes `login_required`, so use one or the other, not both.
Signed-out visitors are redirected to `/login?next=…`; signed-in users without the role
get a *403 Access denied* page. `User.has_role("moderator")` is available in Python and in
templates (`current_user.has_role(...)`).

### 23.7 Navigation and templates

`base.html` provides the header, flash messages and footer for every page. Templates get
`current_user` (the verified `User`, or `None`) from a context processor; it is loaded once
per request.

| Visitor    | Navigation |
| ---------- | ---------- |
| Signed out | Browse, Log in, Register |
| Student    | Browse, Upload, My Notes, account name, Log out |
| Moderator  | the student items + Reports |
| Admin      | the moderator items + Subjects |

Each navigation item is tied to an endpoint name in `auth.NAV_ITEMS` (`notes.browse`,
`notes.upload`, `notes.mine`, `moderation.reports`, `admin.subjects`). An item whose
endpoint does not exist yet is shown greyed out with a "Soon" label; once a route with that
endpoint name is registered, it becomes a working link automatically. Since Phase 4 every
item is a real page.

The pages are plain HTML and CSS (`static/css/style.css`) with no framework and no web
fonts. They use ink (near-black) plus one lime highlight, visible keyboard focus, labelled fields with errors
linked by `aria-describedby`, a skip link, and reduced motion when the OS requests it. The
layout was checked for horizontal scrolling at 320, 375, 414, 768, 1024 and 1440 px.
`static/js/main.js` only adds dismiss buttons to flash messages; every page works without
JavaScript.

### 23.8 CSRF protection

Flask-WTF's `CSRFProtect` is enabled for the whole app: every POST (register, login,
logout, and any future form) must include `{{ csrf_token() }}` in a hidden
`csrf_token` field. Requests without a valid token get a 400 page. Tokens last as long as
the session (`WTF_CSRF_TIME_LIMIT = None`), so a form left open for hours still works.

### 23.9 Running the tests

The tests run against a **separate MySQL database** so they never touch your development
data. They delete every row in it before and after each test.

1. Create the test database and give the app user access (as MySQL root; use
   `'localhost'` instead of `'%'` for a native install, as in section 9):

   ```sql
   CREATE DATABASE IF NOT EXISTS noteshare_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
     ON noteshare_test.* TO 'noteshare_user'@'%';
   ```

2. Add `TEST_DATABASE_URL` to `.env` (section 13). As a safety check, the tests refuse to
   run unless the database name ends in `_test` and differs from `DATABASE_URL`'s.
3. Install the test dependencies and run the tests:

   ```powershell
   python -m pip install -r requirements-dev.txt
   python -m pytest -v
   ```

The tests create their tables in `noteshare_test` and register three test-only routes
(`/_test/student`, `/_test/moderator`, `/_test/admin`) on the test app only; those routes
do not exist when the real app runs. CSRF protection stays on during the tests, which
submit real tokens. They cover registration (valid, each invalid field, duplicate email
including the race-condition path, ignored `role=admin`), login (valid, wrong password,
unknown email, banned), logout (with and without a token, GET refused), `next` redirect
safety, `login_required`, all role combinations, sessions of banned or deleted users,
navigation per role, cookie flags, escaping of user input, and form-value preservation.

### 23.10 Phase 2 limitations

- No password reset, email verification, "remember me", or account editing.
- No login rate limiting or account lockout; add it before a public deployment.
- Promoting or demoting users is done in MySQL. Banning is done from the moderation
  dashboard (section 25.5); un-banning is done in MySQL.
- No Privacy Policy or Terms pages yet; both are needed before a public launch.

## 24. Phase 3: Core Note Features

Phase 3 adds the note workflow in `notes.py` (a blueprint registered by `app.py`). It uses
the existing `notes`, `subjects`, `users` and `ratings` tables unchanged; no schema change
was needed.

### 24.1 Routes

| Route                      | Method    | Access                          | Purpose |
| -------------------------- | --------- | ------------------------------- | ------- |
| `/`                        | GET       | anyone                          | Browse, search, filter, sort and page through active notes |
| `/upload`                  | GET, POST | signed in                       | Upload a note |
| `/note/<id>`               | GET       | anyone (active notes)           | Note details, rating summary and reviews |
| `/note/<id>/download`      | GET       | signed in                       | Download the file |
| `/my-notes`                | GET       | signed in                       | Your own uploads and their status |
| `/note/<id>/delete`        | POST only | the note's uploader             | Delete your note |

### 24.2 Uploading notes

The form asks for a title (required, up to 200 characters), an optional description (up
to 5,000 characters; line breaks are kept), a subject chosen from the `subjects` table, and
a file.

- **Allowed files:** `.pdf`, `.docx`, `.pptx`, `.jpg`, `.png` (`ALLOWED_EXTENSIONS` in
  `config.py`; upper-case extensions are accepted and stored in lower case).
- **Content check:** the file's first bytes must match its extension (PDF, PNG and JPEG
  signatures; `.docx`/`.pptx` must be real Office ZIP packages). A program renamed to
  `.pdf` is rejected. This catches mislabelled files but does not prove a document is
  harmless; uploaded files are never executed or displayed inline.
- **Size limit:** the whole request may be at most 10 MiB (`MAX_CONTENT_LENGTH`). Larger
  uploads get the upload form back with *"This file is larger than the 10 MiB limit"*
  (HTTP 413); the browser also warns before sending when JavaScript is on.
- **Storage:** the file is saved in `UPLOAD_FOLDER` (`uploads/` by default) as
  `<32 hex characters>.<ext>`, a random UUID. The original filename is used only to read
  its extension. `Note.file_path` stores just that name, never a full path, so the folder
  can move between machines.
- The uploader is always the signed-in user (a submitted `uploader_id` is ignored), and new
  notes start as `active` with 0 downloads and a 0 average rating.
- If the database insert fails after the file was saved, the transaction is rolled back,
  the file is removed, and the form is shown again with your entries kept.

### 24.3 Browsing, search, filters, sorting and pagination

The homepage lists **active notes only**; flagged and removed notes never appear.

| Parameter    | Values | Meaning |
| ------------ | ------ | ------- |
| `q`          | text   | Case-insensitive search in titles **and** descriptions (`%` and `_` are matched literally) |
| `semester`   | e.g. `5` | Notes whose subject is in that semester |
| `subject`    | subject id | Notes for one subject |
| `sort`       | `newest` (default), `highest_rated`, `most_downloaded` | Ties are broken by newest upload, then id, so the order is stable |
| `page`       | 1, 2, … | 12 notes per page |

All parameters combine in one SQL query: filters, then ordering, then `LIMIT/OFFSET`, so
`/?q=algorithms&semester=5&subject=1&sort=newest&page=2` returns page 2 of the notes that
match all of them. Pagination links keep every active parameter. Invalid values (e.g.
`semester=abc`, an unknown subject, `page=-1`, an unknown sort) are ignored instead of causing
an error; a page past the end redirects to the last page. Each listing shows a matching
empty state: no notes yet, no search results, or no notes for the selected filters (with a
link to clear them).

### 24.4 Note details and downloads

The detail page shows the title, description, subject (linked to that subject's listing),
semester, uploader, upload date, downloads, file format, the rating summary and every review
(newest first). The summary is calculated from the `ratings` rows themselves, so it cannot
be out of date; with no ratings it says *"No ratings yet."* Review text is escaped, never
rendered as HTML. **Submitting ratings is not part of Phase 3**; this page displays ratings
that already exist.

Downloads require login (signed-out visitors see *"Log in to download"*). The download
route checks the note's visibility, accepts only stored names this app generates, makes
sure the resolved path is inside `UPLOAD_FOLDER` and the file exists, then sends it as an
attachment named after the note's title (e.g. `Graph_Algorithms_Notes.pdf`) with
`X-Content-Type-Options: nosniff`.

**When the download count goes up:** once, for each request that passes every check and
starts sending the file. It is updated in MySQL as `download_count = download_count + 1`,
so simultaneous downloads are all counted. Missing notes, refused requests and missing
files are not counted. A count means "the server started sending the file", not "the user
received all of it", and repeat downloads by the same person count again.

### 24.5 Who can see what

| Note status | Listed on `/` | Detail page and download |
| ----------- | ------------- | ------------------------ |
| `active`    | yes           | everyone can view; signed-in users can download |
| `flagged`, `removed` | no   | only the uploader and moderators/admins; everyone else gets **404**, so hidden notes don't reveal that they exist |

The uploader sees the status on the detail page and in My Notes: **Active**, **Flagged /
Under Review** or **Removed**, shown as text (not by colour alone).

### 24.6 My Notes and deleting

`/my-notes` lists only the signed-in user's own notes (12 per page), with subject, date,
rating, downloads, status, a View link and a Delete button. With no uploads it shows
*"You haven't uploaded any notes yet."* and a link to upload.

Deleting asks for confirmation first (a built-in disclosure, so it works without
JavaScript), is POST-only and CSRF-protected, and is checked on the server: only the note's
uploader may delete it (others get 403, including moderators; a GET request gets 405). The
database row is deleted first; the note's ratings and reports go with it through the
`ON DELETE CASCADE` foreign keys, and nothing belonging to other notes is touched. The file
is removed only after the database commit succeeds, and a file that can't be removed is
logged for manual cleanup. Since Phase 4, a **flagged** note cannot be deleted by its
uploader until a moderator has reviewed it, so its reports are kept.

### 24.7 Search engines, sharing and page quality

- Every page has a unique `<title>`, a meta description, exactly one `<h1>`, Open Graph
  and Twitter tags with a 1200×630 share image (`static/og-image.png`), and favicons
  (`favicon.svg`, `/favicon.ico`, `apple-touch-icon.png`).
- **Canonical links** drop tracking/navigation parameters: note pages point to
  `/note/<id>`, listings to `/?semester=…&subject=…&page=…`.
- **Indexing:** the browse page, semester/subject listings and active notes are indexable.
  Searches, re-sorted lists, login, upload, My Notes, account, hidden notes and error pages
  are `noindex`.
- `/robots.txt` keeps crawlers out of private pages and points to `/sitemap.xml`, which
  lists the homepage, subject listings with active notes, every active note, and
  registration.
- `/llms.txt` gives AI tools a plain-text summary of the site and its subjects.
- **Structured data (JSON-LD):** `WebSite` with a search action on the homepage;
  `LearningResource` (with `AggregateRating` only when real ratings exist) and
  `BreadcrumbList` on note pages. There is deliberately **no `LocalBusiness` markup**:
  NoteShare has no physical address, and inventing one would be false information.
- Breadcrumbs appear on note, upload, My Notes and account pages; the footer links to every
  subject; the 404 page offers a search box and semester links.
- No source maps are shipped, and the only JavaScript is `static/js/main.js` (under 2 KB).

### 24.8 Custom domain

A domain has to be registered and pointed at your web host outside this project. Once
it is live, set `SITE_URL=https://your-domain` in the server's `.env`. Canonical links,
`robots.txt`, `sitemap.xml`, `llms.txt` and share tags will then use it. Without
`SITE_URL`, the address of the current request is used, which is fine locally but should
not be relied on in production. Serve the site over HTTPS and set
`SESSION_COOKIE_SECURE=true` at the same time.

### 24.9 Running the tests

The same setup as section 23.9; uploaded test files go to a temporary folder, never
`uploads/`:

```powershell
python -m pytest -v
```

`tests/test_notes.py` covers uploads (valid PDF, UUID names, uploader/subject/status,
rejected types and disguised files, missing/empty/oversized files, invalid subjects,
preserved form values, cleanup after a database failure), five sample uploads across
semesters 5 and 6 (PDF, DOCX, PPTX, PNG, PDF) that are then downloaded, the homepage
(hidden notes, search in titles and descriptions, every filter combination, all three
sorts, pagination with preserved parameters, empty states, malformed parameters), details,
downloads (login, bytes, counter, missing files, hidden notes, unsafe stored paths) and
My Notes/delete (ownership, cascades, GET refused, CSRF). `tests/test_seo.py` covers the
items in 24.7.

### 24.10 Phase 3 limitations

- Card ratings use the stored `Note.avg_rating`, which the rating route keeps up to date
  (section 25.2); the detail page always calculates from the ratings themselves.
- Content checks catch disguised files but are not a virus scan.

## 25. Phase 4: Ratings, Reports, Moderation, and Subjects

Phase 4 adds rating and report forms to the note page (`notes.py`), a moderation
dashboard (`moderation.py`) and subject administration (`admin.py`). The only schema change
is one new nullable column, `reports.details` (section 25.8).

### 25.1 Routes

| Route | Method | Access | Purpose |
| ----- | ------ | ------ | ------- |
| `/note/<id>/rate` | POST | signed in, not the uploader | Create or update your rating |
| `/note/<id>/report` | POST | signed in, not the uploader | Report a note |
| `/moderation` | GET | moderators, admins | Open reports grouped by note |
| `/moderation/note/<id>/dismiss` | POST | moderators, admins | Close open reports; flagged note becomes active |
| `/moderation/note/<id>/remove` | POST | moderators, admins | Hide the note; close open reports |
| `/moderation/note/<id>/warn` | POST | moderators, admins | Add a warning to the uploader |
| `/moderation/note/<id>/ban` | POST | moderators, admins | Suspend the uploader |
| `/admin/subjects` | GET | admins | List subjects with note counts |
| `/admin/subjects/add` | GET, POST | admins | Add a subject |
| `/admin/subjects/<id>/edit` | GET, POST | admins | Edit a subject |
| `/admin/subjects/<id>/delete` | POST | admins | Delete a subject that has no notes |

Every state-changing route is POST-only (GET gets 405) and needs a CSRF token (missing or
wrong token gets 400). Students get 403 on moderation and subject routes; moderators get 403
on subject routes; signed-out visitors are sent to log in. Banned users are blocked by the
existing `login_required` check on their next request.

### 25.2 Ratings

The note page shows a 1–5 star picker (real radio buttons, so it works with the keyboard
and without JavaScript) and an optional review of up to 1,000 characters.

- Any signed-in, non-banned user can rate an **active** note they did not upload. The author
  is always the signed-in user, stored in `ratings.student_id`; the note comes from the
  URL. Submitted `student_id`/`note_id` fields are ignored.
- Rating your own note shows *"You cannot rate your own note."* and saves nothing.
- Stars must be exactly `1`–`5`; anything else (0, 6, `abc`, `3.5`, missing) is rejected
  with the form values kept.
- **One rating per student per note.** Submitting again updates your stars, review and date
  instead of adding a row. The `uq_ratings_note_student` unique key backs this; if two
  submissions race, the loser is retried as an update.
- After every create or update, `Note.update_avg_rating()` runs **in the same
  transaction**, so the stored average is never out of step with the ratings. The route
  locks the note row first and the average is read with a locking read, so simultaneous
  ratings from different students all count (tested with six at once).
- The note page shows the average, the number of ratings and every review (name, stars,
  comment, date, newest first). With none it says *"No ratings yet."* The homepage cards
  show the stored average.

### 25.3 Reports and automatic flagging

The note page has a **Report this note** form with a required reason (*Wrong subject,
Copied content, Unreadable, Inappropriate, Other*) and optional details (up to 1,000
characters; required for *Other*). Any other reason value is rejected.

- The reason is stored in `reports.reason` and the details in the new `reports.details`
  column. `action_taken` is kept for moderator decisions.
- You cannot report your own note (*"You cannot report your own note."*).
- **One report per student per note**, ever (`uq_reports_note_reporter`). A second attempt
  shows *"You have already reported this note."* Resolved reports are never reopened or
  deleted to allow a new one. After reporting, the page shows when you reported and
  whether a moderator has reviewed it.
- Only **active** notes can be reported. A removed note can never be flagged or
  reactivated by a report.
- New reports are `open`. **When a note has 3 or more open reports, it becomes `flagged`**
  (`FLAG_AT_OPEN_REPORTS` in `config.py`). Resolved reports don't count. This happens in the
  same transaction as the third report. The note row is locked, so simultaneous reports are
  counted one after another: with six students reporting at the same instant, exactly three
  reports were accepted, the note was flagged, and the rest were refused because the note
  was no longer visible to them.
- A flagged note disappears from browse, and ordinary students get 404 for its page and its
  download (enforced in the routes, not just hidden). Its uploader and moderators can still
  open it.
- Students never see who reported a note; reporter names are shown to moderators only.

### 25.4 Moderation dashboard

`/moderation` lists every note that has open reports, **one card per note** with all its
open reports inside. Each card shows:

- the title (linked), subject, uploader (with their warning count) and upload date
- the status, open-report count, average rating and downloads
- each report's reason, details, reporter and date

Order: **flagged notes first**, then the most open reports, then the oldest report, then
note id (10 cards per page). With nothing to review it shows *"No open reports. Everything
is clear."* Loading the cards and their reports takes three queries (count, page of notes, their reports), however many reports there are.

### 25.5 Moderation actions

Each action locks the note, makes all its changes in one transaction (rolled back with a
generic message if anything fails), and appends a line such as
`2026-10-09 16:40 UTC: Dismissed by moderator Rahul Verma (user #2)` to the
`action_taken` history of the affected open reports. Nothing deletes notes, files, ratings,
reports or users.

| Action | What happens |
| ------ | ------------ |
| **Dismiss** | All open reports for the note become `resolved`; a flagged note becomes `active` again and reappears in browse. A removed note stays removed. |
| **Remove** (with confirmation) | Note becomes `removed` (hidden from students; file kept); all its open reports become `resolved`. |
| **Warn uploader** | Uploader's `warnings` goes up by 1. **At 3 warnings the uploader is suspended automatically** (`BAN_AT_WARNINGS`). Reports stay open. The message gives the new count, e.g. *"Warning count: 2 of 3."* |
| **Ban uploader** (with confirmation) | Uploader's `is_banned` becomes true; the account, notes and history are kept. They cannot log in and any existing session is ended on its next request. |

- The uploader is always taken from the note, never from form data.
- **No double warnings:** the warn form carries the warning count the moderator saw, and the
  update only applies if the count is still the same, so a double-click or resubmitted form
  adds one warning, not two. Buttons are also disabled after the first click.
- A moderator cannot warn or ban an **admin**; only an admin can. An admin who bans their
  own account is signed out on their next request.
- **Confirmation:** *Remove note*, *Ban uploader* and subject deletion open an inline
  confirmation panel ("Are you sure you want to remove this note? The note will be hidden
  from students and all open reports will be closed.") with a separate "Yes, …" button. It
  is a built-in `<details>` panel, so it also works without JavaScript. It is a usability
  safeguard; permissions are checked on the server for every request.

### 25.6 Subject administration

`/admin/subjects` (admins only) lists every subject with its code, name, semester and note
count, with Add, Edit and Delete buttons. With no subjects it shows *"No subjects found."*
and an Add button.

- **Code:** required, up to 20 characters, letters/numbers/spaces/hyphens, stored in
  capitals, unique (case-insensitively). A clash shows *"A subject with the code … already
  exists."* (also if two admins race; the unique key catches it).
- **Name:** required, up to 150 characters. **Semester:** 1 to 8.
- Editing keeps the same subject id, so its notes simply show the new code and name.
  Keeping the same code is not treated as a duplicate.
- **Deleting** is POST with CSRF and an inline confirmation, and only works when no notes
  use the subject. Otherwise it shows *"This subject cannot be deleted because notes are
  associated with it."* The `ON DELETE RESTRICT` foreign key enforces the same rule in
  MySQL. Notes are never cascade-deleted.

### 25.7 Other changes

- The uploader of a **flagged** note can no longer delete it until a moderator has
  reviewed it (removed notes can still be deleted by their uploader).
- The account page shows your warning count once you have one.
- The navigation's *Reports* and *Subjects* items now link to the new pages.

### 25.8 Database migration

New column: `reports.details TEXT NULL` (the reporter's explanation). Existing reports are
untouched; their details are empty.

`migrate.py` applies it safely: it checks `information_schema` first, only runs
`ALTER TABLE reports ADD COLUMN details TEXT NULL AFTER reason` when the column is missing,
never drops anything, and does nothing on a second run. `python seed.py` and the test suite
run it automatically; you can also run it on its own:

```powershell
python migrate.py
```

The app's MySQL user already has the `ALTER` privilege on `noteshare` (section 10). Taking
a backup first is still good practice:
`mysqldump -u root -p noteshare > noteshare_backup.sql`. `schema.sql` includes the new
column for fresh installs.

### 25.9 Tests and verification

```powershell
python -m pytest -v
```

`tests/test_phase4.py` drives everything through the real routes with real CSRF tokens
against the MySQL test database:

- **Ratings:** valid, invalid, missing and malformed stars; own note; updates instead of
  duplicates; `update_avg_rating()` called; averages after one, several and changed
  ratings; signed-out and banned users; spoofed ids; escaping; only active notes.
- **Reports:** valid reports stored as `open`; exactly the five reasons; invalid reasons;
  details rules; own note; duplicates; spoofed ids; flagging on the third open report;
  resolved reports not counting; removed notes not reactivated; reporter privacy.
- **Moderation:**
  - access for students, signed-out visitors, moderators and admins
  - ordering and grouping
  - dismiss, remove, warn and ban, including the third-warning ban and double-submit
    protection
  - moderators can't act on admins
  - students, GET requests and forged or missing CSRF tokens change nothing
- **Subjects:** student and moderator access, add/edit/delete, duplicate and invalid
  input, form values kept, notes unaffected by edits, in-use subjects protected.
- **The required end-to-end workflow:**
  1. Three students report one note: after each report the note stays active, then it
     becomes flagged.
  2. It disappears from browse and its download is refused.
  3. The moderator sees it first, with all three reasons and details.
  4. Dismiss makes it active and listed again, while an unrelated open report stays open.
  5. The database keeps all three reports as `resolved`.
- **Concurrency:** six simultaneous reports and six simultaneous ratings against MySQL.
  With the row locks removed as an experiment, both tests failed every time (extra
  reports accepted; database deadlocks on ratings), which confirms the locks are what make
  them pass.
