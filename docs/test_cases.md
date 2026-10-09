# NoteShare test cases

This table lists the main test cases. Every row matches a real pytest test (named in the
Description or listed under TC-18 onwards by file), and the **Pass/Fail column is copied from
the latest test run**, not typed by hand.

**Latest run:** 09 October 2026, 23:58 (local time) on MySQL 8.0.46, command `python -m pytest -v`.
**Whole suite:** 290 tests collected, 290 passed, 0 failed,
0 skipped. Some rows cover several cases of one test (for example TC-03 runs
for both `malware.exe` and `notes.txt`); a row is marked Pass only if all its cases passed.

TC-01 to TC-17 are in `tests/test_app.py`. TC-18 onwards are in the other test files:
TC-18 to TC-20 and TC-28 in `test_auth.py`; TC-21, TC-23, TC-29, TC-30, TC-35 and TC-36 in
`test_notes.py`; TC-22, TC-24 to TC-27 and TC-31 to TC-34 in `test_phase4.py`; TC-37 in
`test_seo.py`; TC-38 to TC-44 in `test_moderation_users.py`.

| Test ID | Description | Input | Expected result | Actual result | Pass/Fail |
| ------- | ----------- | ----- | --------------- | ------------- | --------- |
| TC-01 | Register a new student (`test_register_new_student`) | Name, college email, password `s3cure-pass`, branch, year 3, plus a hidden extra field `role=admin` | Redirect to the login page; user saved with role `student`; password stored only as a hash | Redirected to `/login`; user saved with role `student`, 0 warnings, not banned; the password is stored as a `scrypt:` hash and verifies with `check_password_hash` | Pass |
| TC-02 | Log in with correct details (`test_login_valid_credentials`) | Email and correct password of an existing student | Login succeeds and protected pages open | Redirected to `/` with “Welcome back, Asha Kulkarni.”; `/upload`, `/my-notes` and `/account` all returned 200 | Pass |
| TC-03 | Upload a file type that is not allowed (`test_upload_rejects_invalid_file_type`, 2 cases) | `malware.exe` and `notes.txt` (small in-memory files) | Upload rejected with a clear message; no note saved; no file kept; no internal error shown | HTTP 422 with “This file type isn't allowed. Upload a PDF, DOCX, PPTX, JPG or PNG file.”; 0 notes in the database; upload folder empty; no traceback in the page | Pass |
| TC-04 | Rate the same note twice (`test_rating_again_updates_existing_rating`) | 3 stars + “Decent overview.”, then 5 stars + “Re-read it: excellent.” on another student's note | One rating row, updated to the second values; average recalculated; latest comment shown | Exactly 1 rating row with 5 stars and the new comment; `avg_rating` = 5.0; the page shows only the new comment and “from 1 rating” | Pass |
| TC-05 | Report your own note (`test_student_cannot_report_own_note`) | The uploader submits a report (reason “Copied content”) on their own note | Report rejected with a clear message; nothing saved; note status unchanged | “You cannot report your own note.” shown; 0 reports in the database; note still `active` | Pass |
| TC-06 | Automatic flagging at three reports (`test_note_flagged_after_three_open_reports`) | Three different students report the same note through the report form | Active after reports 1 and 2; flagged after report 3; hidden from browse; download refused | Status `active`, `active`, then `flagged`; 3 open reports; note missing from another student's browse page; its page and download returned 404 | Pass |
| TC-07 | Moderator bans an uploader (`test_moderator_can_ban_uploader`) | A moderator uses Ban uploader (POST with CSRF token) on a student's note | Uploader suspended; account and notes kept; success message; cannot log in; existing session stops working | “Uma Uploader has been suspended and can no longer log in.” shown; `is_banned` = true; user and note still exist; uploader's open session redirected to `/login`; new login refused (403, “Your account has been suspended.”) | Pass |
| TC-08 | Student opens the moderation dashboard (`test_student_cannot_access_moderation`) | A signed-in student requests `GET /moderation` while a report exists | Access refused with HTTP 403; no dashboard content shown | HTTP 403 “Access denied” page; the reporter's name, report details and moderation buttons were not in the response | Pass |
| TC-09 | Statistics bar with an empty database (`test_statistics_show_zero_without_data`) | Homepage with no notes and no subjects | All three totals show 0 and the page still loads | Total notes 0, total downloads 0, total subjects 0; page returned 200 | Pass |
| TC-10 | Statistics follow uploads, downloads, removal and subject changes (`test_statistics_follow_the_database`) | Upload 2 notes; download them 3 and 1 times; a moderator removes the first; an admin deletes an unused subject | Totals always match the database; removed notes and their downloads are not counted | 2 notes / 4 downloads / 6 subjects, then 1 / 1 / 6 after removal, then 5 subjects after the deletion | Pass |
| TC-11 | Statistics ignore the search filters (`test_statistics_are_site_wide_not_filtered`) | Search for a word that matches nothing | Totals still show the whole site | Total notes stayed 1 while the search showed no results | Pass |
| TC-12 | Custom 404 page (`test_404_page_for_visitors_and_signed_in_users`) | `/no/such/page` and `/note/999999`, signed out and signed in | HTTP 404 with “Page not found”, the standard message and a home-page button | All four requests returned 404 with the heading, the message “The page you're looking for doesn't exist or may have been moved.”, a “Go to the home page” button and no traceback | Pass |
| TC-13 | Custom 403 page (`test_403_page_for_signed_in_users_without_permission`) | A student opens `/moderation` and `/admin/subjects` | HTTP 403 with “Access denied”, the standard message and a link to an allowed page | Both returned 403 with “Access denied”, “You don't have permission to access this page.”, a “Browse notes” button and the signed-in name and role | Pass |
| TC-14 | Signed-out visitors are sent to login (`test_signed_out_users_are_sent_to_login_not_403`) | `/moderation`, `/admin/subjects`, `/upload`, `/my-notes` without logging in | Redirect to the login page, not a 403 | All four returned 302 to `/login?next=...` | Pass |
| TC-15 | Unexpected errors stay 500 and hide details (`test_server_errors_are_not_turned_into_404_or_403`) | A simulated bug while building the homepage | HTTP 500 “Something went wrong” page without internal details | HTTP 500 with “Something went wrong”; the error text and traceback were not shown | Pass |
| TC-16 | Empty states on every screen (`test_empty_states_and_their_actions`) | Home (signed out and in), a search with no results, My Notes, a note with no reviews, moderation, subjects with no data | Each screen shows its friendly message; action buttons only for users allowed to use them | All six messages appeared; signed-out home offered “Create a student account” and no upload link; signed-in home offered “Upload a note” | Pass |
| TC-17 | Empty states disappear when data exists (`test_empty_states_are_hidden_when_data_exists`) | Upload one note, then open Home and My Notes | No empty-state message | Neither empty-state message appeared | Pass |
| TC-18 | Registration with an email that already exists | An email already registered, in different letter case with spaces | Rejected with a message; no second account; other fields kept, password not | HTTP 422, “An account with this email already exists.”; still 1 user; name, email, branch and year kept; password not shown | Pass |
| TC-19 | Login with a wrong password | Correct email, wrong password | Generic error; no session; email kept | HTTP 401, “Invalid email or password.”; no user in the session; email field kept | Pass |
| TC-20 | Banned user tries to log in | Correct email and password of a banned account | Login refused with the suspension message | HTTP 403, “Your account has been suspended.”; no session created | Pass |
| TC-21 | Upload while signed out | `GET /upload` and a `POST /upload` with a PDF, signed out | Sent to login; nothing saved | Both redirected to `/login`; 0 notes; no files saved | Pass |
| TC-22 | Students and moderators try subject administration | Student and moderator open the list, add form, edit form, and post add/delete | Every request refused with 403; signed-out visitors sent to login; nothing changed | All returned 403 (signed out: 302 to login); no subject added or deleted | Pass |
| TC-23 | Open a note that does not exist | `GET /note/999999` | HTTP 404 | HTTP 404 | Pass |
| TC-24 | Rate your own note | The uploader submits 5 stars on their own note | Refused with “You cannot rate your own note.”; nothing saved | Message shown; 0 ratings | Pass |
| TC-25 | Report the same note twice | The same student reports a note, then reports it again with another reason | Second report refused; only the first is kept | “You have already reported this note.”; 1 report, reason “Unreadable” | Pass |
| TC-26 | Dismissed reports don't count toward flagging | 2 reports → moderator dismisses → 2 new reports → 1 more | Note stays active with only 2 open reports; flagged at 3 open | Active after 4 total (2 resolved, 2 open); flagged after the 3rd open report; statuses resolved, resolved, open, open, open | Pass |
| TC-27 | Moderation actions need POST and a CSRF token (4 actions) | GET, POST without a token, and POST with a forged token, for dismiss/remove/warn/ban | GET refused (405); missing or forged token refused (400); nothing changes | 405 for GET, 400 for both token cases, note/report/user unchanged for all four actions | Pass |
| TC-28 | Login and registration forms need a CSRF token (2 cases) | POST to `/login` and `/register` without a token | Refused with HTTP 400; no account created | Both returned 400; 0 users | Pass |
| TC-29 | Downloading flagged or removed notes (2 cases) | Another student, the uploader and a moderator download a flagged/removed note | Other students refused; uploader and moderator allowed | Other student 404 with no count increase; uploader 200 with the right file; moderator 200 | Pass |
| TC-30 | Delete another student's note | A different student (and a moderator) posts the delete form | Refused with 403; note and file kept | 403 for both; note and its file still present | Pass |
| TC-31 | Delete a subject that has notes | Admin deletes CS501, which has a note | Refused with the standard message; subject and note unchanged | “This subject cannot be deleted because notes are associated with it.”; subject and note unchanged | Pass |
| TC-32 | End to end: three reports, then the moderator dismisses | Students A, B, C report one note; the moderator opens the dashboard and dismisses | Flagged after the 3rd report and hidden; shown first to the moderator; active again after dismissal; reports kept as resolved | Active, active, flagged; hidden from browse and download; listed first with all three reasons; active and listed again after dismissal; 3 reports kept, all resolved; an unrelated report stayed open | Pass |
| TC-33 | Three warnings suspend the uploader | A moderator warns the same uploader three times | Warnings 1, 2, then 3 with automatic suspension | Warnings 1 and 2 (not banned), then 3 and banned; messages “Warning count: 2 of 3.” and “...suspended automatically” | Pass |
| TC-34 | Six students report at the same moment | Six threads post reports at once | The note is flagged correctly; no extra reports after it is hidden | Exactly 3 reports accepted, 3 refused with 404, note flagged | Pass |
| TC-35 | Five sample uploads across semesters 5 and 6 | PDF, DOCX, PPTX, PNG and PDF for CS501, CS502, CS503, CS601, CS602 | All saved with UUID file names and listed; downloads return the same bytes | 5 notes with the right subjects and UUID names; all 5 listed; every download byte-for-byte identical | Pass |
| TC-36 | Search + semester + subject + sort with pagination | `q=algorithms`, semester 5, subject CS501, newest, 15 matching notes | 12 on page 1, 3 on page 2; links keep every filter | 12 then 3 results; Next/Previous links kept q, semester, subject and sort | Pass |
| TC-37 | Every page has one heading, a unique title and a description | 11 pages: public, signed-in only, a hidden note and a 404 page | Exactly one `<h1>`, a unique `<title>` and a description on each | All pages had one `<h1>`, unique titles ending in “· NoteShare” and a description | Pass |
| TC-38 | Moderator unbans a student (`test_moderator_can_unban_a_student`) | Banned student with 3 warnings; moderator confirms *Unban* on the Users page | Account unbanned; success message; warnings unchanged | `is_banned` = false; “Bina Banned has been unbanned and can log in again.” shown; warnings still 3; redirected back to the Users page | Pass |
| TC-39 | Moderator resets warnings (`test_moderator_can_reset_warnings`) | Student with 2 warnings; moderator confirms *Reset warnings* | Warnings become 0; success message; ban status unchanged | Warnings 0, not banned; “Wasim Warned's warnings have been reset to 0.” shown | Pass |
| TC-40 | Student opens the Users page (`test_student_cannot_open_moderation_users`) | A student requests `/moderation/users` and posts the unban and reset forms directly | Page and actions refused; nothing changes; signed-out visitors sent to login | 403 “Access denied” with no user data; both actions 403; the target kept 2 warnings and stayed banned; signed out: 302 to `/login` | Pass |
| TC-41 | Unbanned student logs in again (`test_unbanned_student_can_log_in_again`) | Banned student tries to log in, a moderator unbans them, they log in again | First login refused; after unbanning, login works and protected pages open | First login 403 “Your account has been suspended.”; after unbanning, login redirected to `/` and My Notes opened (200) | Pass |
| TC-42 | Users page search (5 cases) | “ananya”, “KIRAN@”, “college.example”, “nobody”, “%” | Matches by name or email, any letter case; no matches shows a message; `%` is not a wildcard | Each search listed exactly the expected students; the empty searches showed “No students match” | Pass |
| TC-43 | Users page actions only affect students | Moderator tries to unban / reset another moderator, and a missing user id | Refused with 404; the account is unchanged | Both actions 404; the other moderator kept 2 warnings and stayed banned; unknown id 404 | Pass |
| TC-44 | Unban and reset need POST and a CSRF token (2 cases) | GET, POST without a token, POST with a forged token | 405 for GET, 400 for missing or forged tokens; nothing changes | 405 and 400 as expected for both actions; warnings and ban status unchanged | Pass |

Rows in this table: 44 (44 Pass, 0 Fail, 0 Skipped).

## How to run the tests

The tests use a **separate MySQL database** (`noteshare_test`), never your development
database. They delete every row in it before and after each test, so they refuse to run
unless its name ends in `_test` and it is different from `DATABASE_URL`.

1. Start MySQL (for the Docker setup: `docker start noteshare-mysql`).
2. Make sure `.env` contains `TEST_DATABASE_URL`, for example
   `mysql+pymysql://noteshare_user:<password>@127.0.0.1:3306/noteshare_test`
   (README, section 23.9, shows how to create the database once).
3. Activate the virtual environment and install the test tools:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements-dev.txt
   ```

4. Run everything, or just the main file:

   ```powershell
   python -m pytest -v
   python -m pytest tests/test_app.py -v
   ```

A full run takes about four minutes. Uploaded test files go to a temporary folder,
not `uploads/`.
