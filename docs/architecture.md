# NoteShare architecture

NoteShare is a website where college students share study notes. This page explains how the
project is organised, in three layers, and how a request travels through them.

## The big picture

```
Browser (student, moderator or admin)
   |
   v
Presentation layer:  HTML pages made from Jinja2 templates, CSS, a little JavaScript
   |
   v
Application layer:   Flask routes and checks (login, roles, validation, rules)
   |                                         \
   v                                          \--> uploads/ folder
Data layer:          SQLAlchemy models              (the actual note files,
   |                                                 saved with random names)
   v
MySQL database:      users, subjects, notes, ratings, reports tables
```

Note files are kept on disk in the `uploads/` folder. The database only stores each
file's name, for example `3bb679bd7ece49af8a48cb67782e34f8.pdf`. Files are only sent to
users through the download route, after the checks.

## 1. Presentation layer (what the user sees)

**Files:** `templates/`, `static/css/style.css`, `static/js/main.js`

- **Jinja2 templates** turn data into HTML pages.
  - `base.html` holds the parts every page shares: header, navigation, search box, messages and footer. Every other page builds on it.
  - Small reusable pieces live in `_forms.html` (a form field with its label and error message), `_notes.html` (note cards, star ratings, status labels, page numbers) and `_layout.html` (breadcrumbs).
- **Pages:**
  - for everyone: `home.html` (browse), `note_detail.html`
  - for students: `upload.html`, `my_notes.html`, `account.html`
  - for login: `login.html`, `register.html`
  - for moderators: `moderation.html`
  - for admins: `admin_subjects.html`, `admin_subject_form.html`
  - error pages: `404.html`, `403.html`, and `error.html` for other errors
- **CSS** (one file, no framework) controls the look and the mobile layouts.
- **JavaScript** is optional and small:
  - it adds a close button to messages
  - it warns about files over 10 MiB before uploading
  - it stops a form being submitted twice

  Every page still works with JavaScript turned off.
- **Forms** show a visible label for each field and an error message right under the field.
  They keep what the user typed after an error (except passwords).

## 2. Application layer (the rules)

**Files:** `app.py`, `auth.py`, `notes.py`, `moderation.py`, `admin.py`, `seo.py`, `config.py`

Flask receives each request and sends it to a **route**: a Python function linked to a URL.
The routes are grouped into blueprints, one file per area:

| File | What it handles |
| ---- | --------------- |
| `app.py` | Creates the app, turns on CSRF protection, registers the blueprints, shows the error pages (403, 404, 500 …) |
| `auth.py` | Register, log in, log out, account page; the `login_required` and `role_required` checks; loading the signed-in user |
| `notes.py` | Browse/search/filter/sort, upload, note page, ratings, reports and automatic flagging, download, My Notes, delete |
| `moderation.py` | Moderation dashboard; dismiss, remove, warn and ban actions; the Users page with unban and reset warnings |
| `admin.py` | Adding, editing and deleting subjects (admins only) |
| `seo.py` | `robots.txt`, `sitemap.xml`, `llms.txt`, `favicon.ico` |
| `config.py` | Settings read from `.env` (database address, secret key, upload folder, limits) |

What this layer checks before doing anything:

- **Who you are.** The browser cookie stores only your user id. On every request the app
  reloads you from the database, so a ban or role change takes effect straight away.
- **What you may do.** `@login_required` asks you to log in. `@role_required("moderator")`
  or `("admin")` returns **403 Access denied** to users without that role. Roles are
  ranked: an admin can do everything a moderator can, and a moderator everything a student
  can.
- **Whether your input is valid:** required fields, lengths, allowed file types, a star
  rating from 1 to 5, report reasons from the fixed list, a semester from 1 to 8. The
  server checks everything; the browser's checks are only a convenience.
- **Business rules:**
  - you can't rate or report your own note
  - one rating per student per note (rating again updates it)
  - one report per student per note
  - a note with 3 open reports is flagged
  - 3 warnings ban an account
  - a subject that still has notes can't be deleted
- **Safety:**
  - every form that changes data needs a CSRF token and must use POST
  - passwords are stored only as hashes
  - uploaded files get random names
  - downloads check the note's status first

## 3. Data layer (where data is kept)

**Files:** `models.py`, `schema.sql`, `migrate.py`, `seed.py`

- **SQLAlchemy models** in `models.py` describe the five tables as Python classes, so routes
  work with objects (`note.title`, `note.uploader.name`) instead of writing SQL by hand.
- **MySQL** stores the data:

| Table | Holds | Linked to |
| ----- | ----- | --------- |
| `users` | name, email, password hash, role (student/moderator/admin), branch, year, warnings, banned flag | uploads, ratings and reports |
| `subjects` | code, name, semester | notes |
| `notes` | title, description, stored file name, subject, uploader, date, average rating, downloads, status (active/flagged/removed) | ratings and reports |
| `ratings` | note, student, stars (1–5), comment, date | one per student per note |
| `reports` | note, reporter, reason, details, status (open/resolved), moderator actions, date | one per student per note |

- **The database enforces the important rules itself**, so they hold even if the code has
  a bug:
  - unique emails and subject codes
  - one rating, and one report, per student per note
  - stars between 1 and 5
  - fixed lists of roles and statuses
  - links between tables that MySQL checks (for example, a subject with notes can't be
    deleted)
- `schema.sql` is the same design written as plain SQL, for documentation.
- `seed.py` creates the tables and the test accounts and subjects.
- `migrate.py` adds later columns to older databases, safely.

## How a request flows, step by step

1. **The user opens a page or submits a form**, for example clicks "Submit report".
2. **Flask receives the request** and finds the matching route, here `report()` in `notes.py`.
3. **The route checks the request:**
   - the CSRF token is valid
   - the user is logged in and not banned
   - the note exists and the user may see it
   - the user isn't the uploader and hasn't already reported it
   - the reason is on the list
4. **The data layer reads or updates the database.** The new report is saved, the open
   reports are counted, and at three the note's status becomes `flagged`, all in one
   transaction. The note row is locked while this happens, so two reports arriving at the
   same moment are counted correctly.
5. **Flask replies.** After a change it sends a redirect with a message such as "Report
   submitted…". After an error it shows the same page again with the message next to the
   field.
6. **The browser shows the result.**

## Two more examples

**Uploading a note**
1. Flask checks the title, the subject (it must exist in the database) and the file. The
   extension must be on the allowed list, the file's first bytes must match that type, and
   the file must be under 10 MiB.
2. The file is saved in `uploads/` under a random name.
3. A `notes` row is created, with you as the uploader and status `active`.
4. If saving the row fails, the file is deleted again so nothing is left half-done.

**Downloading a note**
1. Flask checks that you are logged in.
2. It checks the note is visible to you: active notes for everyone, hidden ones only for
   the uploader and moderators.
3. It checks the stored name is one the app created, and that the file exists inside
   `uploads/`.
4. It adds one to the download count in the database, then sends the file as a download.

## How the layers work together

- The **presentation layer never talks to the database**. It only shows what the routes
  give it.
- The **application layer** decides everything: who can do what, and what is valid. It uses
  the models to read and change data.
- The **data layer** stores data and protects it with constraints, so the most important
  rules hold even if a check were missed in the code.

Keeping these jobs apart means a page's look can change without touching the rules, and
the rules can change without touching the database design.

## Tests

The `tests/` folder checks all three layers through the real routes, using a separate
`noteshare_test` database:
- `test_app.py` holds the main scenarios
- `test_auth.py`, `test_notes.py`, `test_phase4.py` and `test_seo.py` go into detail

See `test_cases.md` for the results.
