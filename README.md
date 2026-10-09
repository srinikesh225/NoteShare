# NoteShare

## 1. Project overview

NoteShare is a peer-to-peer notes marketplace for college students: students upload their
academic notes, find notes for their subjects, rate them, and report inappropriate content
to moderators.

The application is built with Flask and MySQL and is being developed in phases. This
repository currently contains:

- **Phase 1: the project foundation and database layer** (sections 2–22)
- **Phase 2: authentication and roles** ([section 23](#23-phase-2-authentication-and-roles))

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
│   ├── base.html         # Layout: header, navigation, flash messages, footer
│   ├── _forms.html       # Form field macro (label, input, inline error)
│   ├── register.html
│   ├── login.html
│   ├── account.html      # Signed-in landing page (your account details)
│   └── error.html        # 400/403/404/405/500 pages
├── static/
│   ├── css/style.css
│   ├── js/main.js        # Optional: dismiss buttons on flash messages
│   └── favicon.svg
├── tests/
│   ├── conftest.py       # Test app, test-database guard, fixtures
│   └── test_auth.py
└── uploads/              # Future uploaded files; contents are git-ignored
```

`uploads/.gitkeep` is an empty placeholder so Git keeps the folder.

Import direction (no circular imports): `app.py → auth.py, config.py, models.py`;
`auth.py → models.py`; `seed.py → app.py, models.py`.

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
TEST_DATABASE_URL=mysql+pymysql://noteshare_user:<YOUR_APP_DB_PASSWORD>@localhost:3306/noteshare_test
```

`SESSION_COOKIE_SECURE` must be `true` in production behind HTTPS, and `false` for local
`http://` development (otherwise the browser drops the session cookie and logins don't stick).
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
starts on <http://127.0.0.1:5000>, which redirects to the login page. Creating the app does
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

Phase 1 contained no pages or routes; Phase 2 added registration, login, logout and the
account page (section 23). The following still do **not** exist:

- Note upload or download endpoints
- Search or browsing
- Ratings UI
- Reporting UI
- Moderation dashboard
- Administrative dashboard

There are also no database migrations yet: `seed.py` creates missing tables but does not
alter existing ones. If a later phase changes a model, adopt a migration tool
(e.g. Flask-Migrate) at that point.

## 23. Phase 2: Authentication and Roles

Phase 2 adds accounts, sign-in and role-based access control. The code lives in `auth.py`
(a Flask blueprint); `app.py` registers it. No database schema change was needed: Phase 2
uses the existing `users` table as it is.

### 23.1 Routes

| Route       | Method    | Access              | Purpose |
| ----------- | --------- | ------------------- | ------- |
| `/`         | GET       | anyone              | Redirects to `/account` if signed in, otherwise `/login` (there is no homepage yet) |
| `/register` | GET, POST | signed-out visitors | Create a student account |
| `/login`    | GET, POST | signed-out visitors | Sign in |
| `/logout`   | POST only | anyone              | Sign out |
| `/account`  | GET       | signed-in users     | Your account details; where users land after signing in |

Signed-in users who open `/login` or `/register` are sent to `/account`.

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
| Signed out | Log in, Register |
| Student    | Browse, Upload, My Notes, account name, Log out |
| Moderator  | the student items + Reports |
| Admin      | the moderator items + Subjects |

Browse, Upload, My Notes, Reports, Subjects and the search box are not built yet. They are
shown greyed out with a "Soon" label (the search box is disabled) instead of linking to
pages that don't exist. Each is tied to an endpoint name in `auth.NAV_ITEMS` /
`auth.SEARCH_ENDPOINT` (`notes.browse`, `notes.upload`, `notes.mine`,
`moderation.reports`, `admin.subjects`, `notes.search`). When a later phase registers a
route with that endpoint name, the item turns into a working link automatically.

The pages are plain HTML and CSS (`static/css/style.css`) with no framework and no web
fonts. They have one accent colour, visible keyboard focus, labelled fields with errors
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
- Promoting, demoting and banning users is done in MySQL until the admin and moderation
  tools exist.
- There is no homepage yet: `/` redirects to `/account` or `/login`.
- No Privacy Policy or Terms pages yet; both are needed before a public launch.
