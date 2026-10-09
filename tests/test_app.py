"""
Main application tests (Phase 5).

The eight required scenarios come first, then the statistics bar, the custom
403/404 pages and the empty states. Everything goes through the real routes
with Flask's test client and real CSRF tokens, against the separate MySQL
test database configured in conftest.py (never the development database).

More detailed tests for each area live in test_auth.py, test_notes.py,
test_phase4.py and test_seo.py; docs/test_cases.md lists them all.
"""

import html
import os
import re

import pytest
from werkzeug.security import check_password_hash

from models import Note, Rating, Report, User, db
from tests.conftest import get_csrf_token, log_in, upload_note

PASSWORD = "correct-password"


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

def text_of(response):
    return html.unescape(response.get_data(as_text=True))


def card_titles(response):
    raw = response.get_data(as_text=True)
    return [html.unescape(t) for t in re.findall(r'<h2 class="note-card-title" title="[^"]*">(.*?)</h2>', raw)]


def post(client, path, data=None, token_page="/"):
    return client.post(path, data={"csrf_token": get_csrf_token(client, token_page), **(data or {})})


@pytest.fixture
def person(app, make_user):
    """Create a user and return a test client already signed in as them."""
    def _person(email, role="student", name=None):
        user_id = make_user(email=email, role=role, name=name or email.split("@")[0].title())
        client = app.test_client()
        assert log_in(client, email, PASSWORD).status_code == 302
        client.user_id = user_id
        return client
    return _person


@pytest.fixture
def shared_note(app, person, subjects):
    """A note uploaded by one student; returns (uploader_client, note_id)."""
    uploader = person("uploader@college.example", name="Uma Uploader")
    response = upload_note(uploader, "Graph Algorithms Notes", subjects["CS501"])
    assert response.status_code == 302
    return uploader, int(response.headers["Location"].rsplit("/", 1)[1])


def get_note(app, note_id):
    with app.app_context():
        note = db.session.get(Note, note_id)
        db.session.expunge(note)
        return note


# ---------------------------------------------------------------------------
# Required test 1: registration
# ---------------------------------------------------------------------------

def test_register_new_student(app, client):
    page = client.get("/register")
    assert page.status_code == 200
    assert 'name="email"' in page.get_data(as_text=True)

    response = post(client, "/register", {
        "name": "Ananya Test", "email": "ananya@college.example", "password": "s3cure-pass",
        "branch": "Computer Science and Engineering", "year": "3",
        "role": "admin",  # a malicious extra field must be ignored
    }, token_page="/register")
    assert response.status_code == 302 and response.headers["Location"] == "/login"

    with app.app_context():
        user = User.query.filter_by(email="ananya@college.example").one()
        assert user.role == "student", "public registration must only create students"
        assert user.password_hash != "s3cure-pass", "password must not be stored in plain text"
        assert user.password_hash.startswith("scrypt:")
        assert check_password_hash(user.password_hash, "s3cure-pass")
        assert (user.warnings, user.is_banned) == (0, False)


# ---------------------------------------------------------------------------
# Required test 2: login
# ---------------------------------------------------------------------------

def test_login_valid_credentials(client, make_user, subjects):
    make_user(email="asha@college.example", password=PASSWORD, name="Asha Kulkarni")
    response = log_in(client, "asha@college.example", PASSWORD)
    assert response.status_code == 302 and response.headers["Location"] == "/"

    home = client.get("/")
    assert home.status_code == 200
    assert "Welcome back, Asha Kulkarni." in text_of(home)
    for protected in ("/upload", "/my-notes", "/account"):
        assert client.get(protected).status_code == 200, f"{protected} should be open after login"


# ---------------------------------------------------------------------------
# Required test 3: invalid file type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename, content", [
    ("malware.exe", b"MZ\x90\x00 not a document"),
    ("notes.txt", b"plain text notes"),
])
def test_upload_rejects_invalid_file_type(app, person, subjects, filename, content):
    # The test relies on the application's own allow-list, not on its own list.
    extension = filename.rsplit(".", 1)[1]
    assert extension not in app.config["ALLOWED_EXTENSIONS"]

    student = person("asha@college.example")
    response = upload_note(student, "Bad upload", subjects["CS501"], filename=filename, data=content)
    body = text_of(response)
    assert response.status_code == 422
    assert "This file type isn't allowed. Upload a PDF, DOCX, PPTX, JPG or PNG file." in body
    assert "Traceback" not in body and "Error 500" not in body
    with app.app_context():
        assert Note.query.count() == 0, "no note record may be created"
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == [], "no file may be kept"


# ---------------------------------------------------------------------------
# Required test 4: rating twice
# ---------------------------------------------------------------------------

def test_rating_again_updates_existing_rating(app, person, shared_note):
    _, note_id = shared_note
    rater = person("rater@college.example", name="Ravi Rater")

    first = post(rater, f"/note/{note_id}/rate", {"stars": "3", "comment": "Decent overview."})
    second = post(rater, f"/note/{note_id}/rate", {"stars": "5", "comment": "Re-read it: excellent."})
    assert first.status_code == 302 and second.status_code == 302

    with app.app_context():
        ratings = Rating.query.filter_by(note_id=note_id, student_id=rater.user_id).all()
        assert len(ratings) == 1, "the second rating must update, not duplicate"
        assert (ratings[0].stars, ratings[0].comment) == (5, "Re-read it: excellent.")
    assert get_note(app, note_id).avg_rating == 5.0

    body = text_of(rater.get(f"/note/{note_id}"))
    assert "Re-read it: excellent." in body and "Decent overview." not in body
    assert "from 1 rating" in body


# ---------------------------------------------------------------------------
# Required test 5: reporting one's own note
# ---------------------------------------------------------------------------

def test_student_cannot_report_own_note(app, shared_note):
    uploader, note_id = shared_note
    response = post(uploader, f"/note/{note_id}/report", {"reason": "copied", "details": "Testing"})
    assert response.status_code == 302
    assert "You cannot report your own note." in text_of(uploader.get(f"/note/{note_id}"))
    with app.app_context():
        assert Report.query.count() == 0
    assert get_note(app, note_id).status == "active"


# ---------------------------------------------------------------------------
# Required test 6: automatic flagging at three reports
# ---------------------------------------------------------------------------

def test_note_flagged_after_three_open_reports(app, person, shared_note):
    _, note_id = shared_note
    reader = person("reader@college.example")
    reporters = [person(f"reporter{i}@college.example") for i in (1, 2, 3)]

    for count, reporter in enumerate(reporters, start=1):
        assert post(reporter, f"/note/{note_id}/report", {"reason": "unreadable"}).status_code == 302
        expected = "active" if count < 3 else "flagged"
        assert get_note(app, note_id).status == expected, f"after report {count}"

    assert "Graph Algorithms Notes" not in card_titles(reader.get("/"))
    assert reader.get(f"/note/{note_id}/download", buffered=True).status_code == 404
    assert reader.get(f"/note/{note_id}").status_code == 404
    with app.app_context():
        assert Report.query.filter_by(note_id=note_id, status="open").count() == 3


# ---------------------------------------------------------------------------
# Required test 7: moderator ban
# ---------------------------------------------------------------------------

def test_moderator_can_ban_uploader(app, person, shared_note):
    uploader, note_id = shared_note        # the uploader is signed in already
    moderator = person("mod@college.example", role="moderator", name="Mona Moderator")

    response = post(moderator, f"/moderation/note/{note_id}/ban", token_page="/moderation")
    assert response.status_code == 302
    assert "Uma Uploader has been suspended and can no longer log in." in text_of(moderator.get("/moderation"))

    with app.app_context():
        user = db.session.get(User, uploader.user_id)
        assert user.is_banned is True
        assert user.email == "uploader@college.example"          # account preserved
        assert db.session.get(Note, note_id) is not None          # notes preserved

    # The existing session is refused on its next protected request...
    response = uploader.get("/my-notes")
    assert response.status_code == 302 and response.headers["Location"] == "/login"
    # ...and a fresh login is refused.
    response = log_in(app.test_client(), "uploader@college.example", PASSWORD)
    assert response.status_code == 403
    assert "Your account has been suspended." in text_of(response)


# ---------------------------------------------------------------------------
# Required test 8: students cannot open moderation
# ---------------------------------------------------------------------------

def test_student_cannot_access_moderation(app, person, shared_note):
    _, note_id = shared_note
    reporter = person("reporter@college.example", name="Riya Reporter")
    post(reporter, f"/note/{note_id}/report", {"reason": "other", "details": "Secret detail text"})

    student = person("student@college.example")
    response = student.get("/moderation")
    body = text_of(response)
    assert response.status_code == 403
    assert "Access denied" in body
    # Nothing from the dashboard leaks into the response.
    for leaked in ("Riya Reporter", "Secret detail text", "Dismiss reports", "Ban uploader"):
        assert leaked not in body


# ---------------------------------------------------------------------------
# Home page statistics bar
# ---------------------------------------------------------------------------

def stats_on_page(response):
    raw = response.get_data(as_text=True)
    values = {}
    for label in ("Total notes", "Total downloads", "Total subjects"):
        match = re.search(rf"<dt>{label}</dt>\s*<dd>([\d,]+)</dd>", raw)
        assert match, f"{label} missing from the statistics bar"
        values[label] = int(match.group(1).replace(",", ""))
    return values


def test_statistics_show_zero_without_data(client):
    assert stats_on_page(client.get("/")) == {"Total notes": 0, "Total downloads": 0, "Total subjects": 0}


def test_statistics_follow_the_database(app, person, subjects):
    uploader = person("uploader@college.example")
    ids = []
    for title in ("Note one", "Note two"):
        response = upload_note(uploader, title, subjects["CS501"])
        ids.append(int(response.headers["Location"].rsplit("/", 1)[1]))
    reader = person("reader@college.example")
    for _ in range(3):
        reader.get(f"/note/{ids[0]}/download", buffered=True)
    reader.get(f"/note/{ids[1]}/download", buffered=True)
    assert stats_on_page(reader.get("/")) == {"Total notes": 2, "Total downloads": 4, "Total subjects": 6}

    # A moderator removes the first note: its notes and downloads drop out.
    moderator = person("mod@college.example", role="moderator")
    post(moderator, f"/moderation/note/{ids[0]}/remove", token_page="/moderation")
    assert stats_on_page(reader.get("/")) == {"Total notes": 1, "Total downloads": 1, "Total subjects": 6}

    # An admin deletes an unused subject.
    admin = person("admin@college.example", role="admin")
    post(admin, f"/admin/subjects/{subjects['CS603']}/delete", token_page="/admin/subjects")
    assert stats_on_page(reader.get("/"))["Total subjects"] == 5


def test_statistics_are_site_wide_not_filtered(person, subjects):
    uploader = person("uploader@college.example")
    upload_note(uploader, "Only note", subjects["CS501"])
    filtered = uploader.get("/", query_string={"q": "no such note"})
    assert stats_on_page(filtered)["Total notes"] == 1


# ---------------------------------------------------------------------------
# Custom 403 and 404 pages
# ---------------------------------------------------------------------------

def test_404_page_for_visitors_and_signed_in_users(person, client):
    for who in (client, person("asha@college.example")):
        for path in ("/no/such/page", "/note/999999"):
            response = who.get(path)
            body = text_of(response)
            assert response.status_code == 404, path
            assert "<h1" in response.get_data(as_text=True) and "Page not found" in body
            assert "The page you're looking for doesn't exist or may have been moved." in body
            assert 'href="/">Go to the home page</a>' in response.get_data(as_text=True)
            assert "Traceback" not in body


def test_403_page_for_signed_in_users_without_permission(person):
    student = person("asha@college.example", name="Asha Kulkarni")
    for path in ("/moderation", "/admin/subjects"):
        response = student.get(path)
        body = text_of(response)
        assert response.status_code == 403, path
        assert "Access denied" in body
        assert "You don't have permission to access this page." in body
        assert 'href="/">Browse notes</a>' in response.get_data(as_text=True)
        assert "Asha Kulkarni (student)" in body


def test_signed_out_users_are_sent_to_login_not_403(client):
    for path in ("/moderation", "/admin/subjects", "/upload", "/my-notes"):
        response = client.get(path)
        assert response.status_code == 302 and response.headers["Location"].startswith("/login"), path


def test_server_errors_are_not_turned_into_404_or_403(app, person, subjects, monkeypatch):
    student = person("asha@college.example")

    def broken(*args, **kwargs):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr("notes.site_statistics", broken)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        response = student.get("/")
    finally:
        app.config["PROPAGATE_EXCEPTIONS"] = None
    assert response.status_code == 500
    body = text_of(response)
    assert "Something went wrong" in body and "simulated bug" not in body and "Traceback" not in body


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------

def test_empty_states_and_their_actions(app, person, client, subjects):
    # Home, signed out: no upload button, a register button instead.
    body = text_of(client.get("/"))
    assert "No notes yet. Be the first to upload!" in body
    assert "Create a student account" in body and 'href="/upload"' not in client.get("/").get_data(as_text=True)

    student = person("asha@college.example")
    raw = student.get("/").get_data(as_text=True)
    assert "No notes yet. Be the first to upload!" in html.unescape(raw) and 'href="/upload">Upload a note</a>' in raw

    body = text_of(student.get("/", query_string={"q": "nothing like this"}))
    assert "No notes match your search." in body and "Try changing your search or filters." in body

    body = text_of(student.get("/my-notes"))
    assert "You haven't uploaded any notes yet." in body and "Upload your first note to get started." in body

    response = upload_note(student, "Lonely note", subjects["CS501"])
    note_id = int(response.headers["Location"].rsplit("/", 1)[1])
    other = person("other@college.example")
    body = text_of(other.get(f"/note/{note_id}"))
    assert "No reviews yet. Be the first to rate this note." in body

    moderator = person("mod@college.example", role="moderator")
    assert "No open reports. Everything is clear." in text_of(moderator.get("/moderation"))

    admin = person("admin@college.example", role="admin")
    with app.app_context():
        db.session.execute(db.text("DELETE FROM notes"))
        db.session.execute(db.text("DELETE FROM subjects"))
        db.session.commit()
    body = text_of(admin.get("/admin/subjects"))
    assert "No subjects found." in body and "Add your first subject" in body


def test_empty_states_are_hidden_when_data_exists(person, subjects):
    student = person("asha@college.example")
    upload_note(student, "Present note", subjects["CS501"])
    assert "No notes yet" not in text_of(student.get("/"))
    assert "You haven't uploaded any notes yet." not in text_of(student.get("/my-notes"))
