"""Authentication, session and role tests (run against the MySQL test database)."""

import html

import pytest
from werkzeug.security import check_password_hash

import auth
from conftest import get_csrf_token, log_in
from models import User, db

VALID_REGISTRATION = {
    "name": "Ananya Test",
    "email": "ananya@college.example",
    "password": "s3cure-pass",
    "branch": "Computer Science and Engineering",
    "year": "3",
}


def register(client, **overrides):
    data = {**VALID_REGISTRATION, **overrides}
    data["csrf_token"] = get_csrf_token(client, "/register")
    return client.post("/register", data=data)


def page(response):
    return html.unescape(response.get_data(as_text=True))


def user_count(app):
    with app.app_context():
        return User.query.count()


def session_user_id(client):
    with client.session_transaction() as sess:
        return sess.get("user_id")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_01_valid_registration_creates_student_with_hashed_password(app, client):
    response = register(client)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"

    with app.app_context():
        user = User.query.filter_by(email="ananya@college.example").one()
        assert user.role == "student"
        assert user.password_hash != VALID_REGISTRATION["password"]
        assert VALID_REGISTRATION["password"] not in user.password_hash
        assert check_password_hash(user.password_hash, VALID_REGISTRATION["password"])
        assert (user.name, user.branch, user.year) == ("Ananya Test", "Computer Science and Engineering", 3)
        assert user.warnings == 0 and user.is_banned is False

    follow = client.get("/login")
    assert "Registration successful! You can now log in." in page(follow)


def test_02_short_password_rejected_and_other_values_kept(app, client):
    response = register(client, password="short7!")
    body = page(response)
    assert response.status_code == 422
    assert "Password must contain at least 8 characters." in body
    assert user_count(app) == 0
    assert 'value="Ananya Test"' in body
    assert 'value="ananya@college.example"' in body
    assert 'value="Computer Science and Engineering"' in body
    assert '<option value="3" selected>' in body
    assert "short7!" not in body


@pytest.mark.parametrize("bad_email", ["not-an-email", "name@", "@college.example",
                                       "name@localhost", "two@@college.example", "a b@college.example"])
def test_03_invalid_email_rejected(app, client, bad_email):
    response = register(client, email=bad_email)
    assert response.status_code == 422
    assert "Enter a valid email address" in page(response)
    assert user_count(app) == 0


def test_04_duplicate_email_rejected_and_values_kept(app, client, make_user):
    make_user(email="ananya@college.example")
    # Different case and surrounding spaces still count as the same email.
    response = register(client, email="  Ananya@College.Example ", name="Second Person", branch="IT", year="2")
    body = page(response)
    assert response.status_code == 422
    assert "An account with this email already exists." in body
    assert user_count(app) == 1
    assert 'value="Second Person"' in body
    assert 'value="ananya@college.example"' in body
    assert 'value="IT"' in body
    assert '<option value="2" selected>' in body
    assert VALID_REGISTRATION["password"] not in body


def test_04a_duplicate_email_reported_together_with_other_errors(app, client, make_user):
    make_user(email="ananya@college.example")
    body = page(register(client, password="short", branch=""))
    assert "An account with this email already exists." in body
    assert "Password must contain at least 8 characters." in body
    assert "Please enter your branch." in body


def test_04b_duplicate_caught_by_mysql_unique_key(app, client, make_user, monkeypatch):
    """If two sign-ups race past the pre-check, MySQL's unique key still wins
    and the transaction is rolled back cleanly."""
    make_user(email="ananya@college.example")
    monkeypatch.setattr(auth, "_email_registered", lambda email: False)
    response = register(client)
    assert response.status_code == 422
    assert "An account with this email already exists." in page(response)
    assert user_count(app) == 1


def test_05_submitted_role_and_status_fields_are_ignored(app, client):
    register(client, role="admin", is_banned="1", warnings="7")
    register(client, email="mod@college.example", role="moderator")
    with app.app_context():
        users = {u.email: u for u in User.query.all()}
        assert users["ananya@college.example"].role == "student"
        assert users["ananya@college.example"].is_banned is False
        assert users["ananya@college.example"].warnings == 0
        assert users["mod@college.example"].role == "student"


@pytest.mark.parametrize("field, value, message", [
    ("name", "   ", "Please enter your name."),
    ("name", "x" * 101, "Name must be 100 characters or fewer."),
    ("branch", "", "Please enter your branch."),
    ("year", "", "Please select your year."),
    ("year", "three", "Enter a valid college year"),
    ("year", "0", "Enter a valid college year"),
    ("year", "7", "Enter a valid college year"),
    ("password", "", "Please choose a password."),
])
def test_registration_field_validation(app, client, field, value, message):
    response = register(client, **{field: value})
    assert response.status_code == 422
    assert message in page(response)
    assert user_count(app) == 0


def test_registration_trims_whitespace_and_lowercases_email(app, client):
    register(client, name="  Ananya   Test ", email=" ANANYA@College.Example ", branch="  CSE  ")
    with app.app_context():
        user = User.query.one()
        assert (user.name, user.email, user.branch) == ("Ananya Test", "ananya@college.example", "CSE")


def test_submitted_values_are_html_escaped(client):
    response = register(client, name="<script>alert(1)</script>", password="short")
    raw = response.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in raw
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in raw


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_06_valid_login_creates_session_and_redirects(client, make_user):
    user_id = make_user(email="asha@college.example", password="correct-password")
    response = log_in(client, "  ASHA@college.example ", "correct-password")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert session_user_id(client) == user_id

    follow = client.get("/account")
    assert follow.status_code == 200
    assert "Welcome back, Asha Kulkarni." in page(follow)


def test_07_wrong_password_rejected_with_generic_message(client, make_user):
    make_user(email="asha@college.example", password="correct-password")
    response = log_in(client, "asha@college.example", "wrong-password")
    body = page(response)
    assert response.status_code == 401
    assert "Invalid email or password." in body
    assert session_user_id(client) is None
    assert 'value="asha@college.example"' in body


def test_07b_unknown_email_gets_the_same_generic_message(client):
    response = log_in(client, "nobody@college.example", "whatever-password")
    assert response.status_code == 401
    assert "Invalid email or password." in page(response)
    assert session_user_id(client) is None


def test_08_banned_user_cannot_log_in(client, make_user):
    make_user(email="banned@college.example", password="correct-password", is_banned=True)
    response = log_in(client, "banned@college.example", "correct-password")
    assert response.status_code == 403
    assert "Your account has been suspended." in page(response)
    assert session_user_id(client) is None


def test_login_requires_both_fields(client):
    response = client.post("/login", data={"csrf_token": get_csrf_token(client, "/login")})
    body = page(response)
    assert response.status_code == 422
    assert "Please enter your email." in body
    assert "Please enter your password." in body


def test_login_clears_previous_session_data(client, make_user):
    make_user()
    with client.session_transaction() as sess:
        sess["planted"] = "value from before login"
    log_in(client, "asha@college.example", "correct-password")
    with client.session_transaction() as sess:
        assert "planted" not in sess
        assert set(sess.keys()) <= {"user_id", "_flashes", "csrf_token"}
        assert "password" not in str(dict(sess)).lower()


def test_login_honours_safe_next_url(client, make_user):
    make_user()
    response = log_in(client, "asha@college.example", "correct-password", next_url="/_test/student?tab=1")
    assert response.headers["Location"] == "/_test/student?tab=1"


@pytest.mark.parametrize("evil", ["https://evil.example/", "//evil.example/", "/\\evil.example",
                                  "javascript:alert(1)", "/login", "http:/evil.example"])
def test_login_rejects_unsafe_next_url(client, make_user, evil):
    make_user()
    response = log_in(client, "asha@college.example", "correct-password", next_url=evil)
    assert response.headers["Location"] == "/"


def test_signed_in_user_visiting_login_or_register_is_redirected(client, make_user):
    make_user()
    log_in(client, "asha@college.example", "correct-password")
    assert client.get("/login").headers["Location"] == "/"
    assert client.get("/register").headers["Location"] == "/"


# ---------------------------------------------------------------------------
# Logout and CSRF
# ---------------------------------------------------------------------------

def test_09_logout_clears_session(client, make_user):
    make_user()
    log_in(client, "asha@college.example", "correct-password")
    token = get_csrf_token(client, "/account")
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert session_user_id(client) is None
    assert "You have been logged out successfully." in page(client.get("/login"))
    assert client.get("/_test/student").status_code == 302


def test_10_logout_without_csrf_token_is_rejected(client, make_user):
    user_id = make_user()
    log_in(client, "asha@college.example", "correct-password")
    response = client.post("/logout")
    assert response.status_code == 400
    assert "This form has expired or did not come from NoteShare." in page(response)
    assert session_user_id(client) == user_id


def test_logout_via_get_is_not_allowed(client, make_user):
    user_id = make_user()
    log_in(client, "asha@college.example", "correct-password")
    assert client.get("/logout").status_code == 405
    assert session_user_id(client) == user_id


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_forms_without_csrf_token_are_rejected(app, client, path):
    response = client.post(path, data={**VALID_REGISTRATION})
    assert response.status_code == 400
    assert user_count(app) == 0


# ---------------------------------------------------------------------------
# login_required
# ---------------------------------------------------------------------------

def test_11_protected_route_redirects_anonymous_user_to_login(client):
    response = client.get("/_test/student?x=1")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login?next=/_test/student?x%3D1"


def test_12_protected_route_allows_valid_session(client, make_user):
    make_user()
    log_in(client, "asha@college.example", "correct-password")
    response = client.get("/_test/student")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "student area"


def test_13_user_banned_after_login_loses_access(app, client, make_user):
    user_id = make_user()
    log_in(client, "asha@college.example", "correct-password")
    assert client.get("/_test/student").status_code == 200

    with app.app_context():
        db.session.get(User, user_id).is_banned = True
        db.session.commit()

    response = client.get("/_test/student")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert session_user_id(client) is None
    assert "Your account has been suspended." in page(client.get("/login"))


def test_deleted_user_session_is_invalid(app, client, make_user):
    user_id = make_user()
    log_in(client, "asha@college.example", "correct-password")
    with app.app_context():
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()
    response = client.get("/_test/student")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert session_user_id(client) is None


def test_forged_session_user_id_is_rejected(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
    assert client.get("/_test/student").status_code == 302


# ---------------------------------------------------------------------------
# role_required
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role, path, expected", [
    ("student", "/_test/student", 200),
    ("student", "/_test/moderator", 403),    # test 14
    ("student", "/_test/admin", 403),
    ("moderator", "/_test/student", 200),
    ("moderator", "/_test/moderator", 200),  # test 15
    ("moderator", "/_test/admin", 403),      # test 16
    ("admin", "/_test/student", 200),
    ("admin", "/_test/moderator", 200),      # test 17
    ("admin", "/_test/admin", 200),          # test 18
])
def test_14_to_18_role_access(client, make_user, role, path, expected):
    make_user(email=f"{role}@college.example", role=role)
    log_in(client, f"{role}@college.example", "correct-password")
    response = client.get(path)
    assert response.status_code == expected
    if expected == 403:
        assert "Access denied" in page(response)


def test_role_route_redirects_anonymous_user_to_login(client):
    response = client.get("/_test/admin")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_role_change_in_database_applies_on_next_request(app, client, make_user):
    user_id = make_user(role="moderator")
    log_in(client, "asha@college.example", "correct-password")
    assert client.get("/_test/moderator").status_code == 200
    with app.app_context():
        db.session.get(User, user_id).role = "student"
        db.session.commit()
    assert client.get("/_test/moderator").status_code == 403


def test_role_required_rejects_unknown_role_name():
    with pytest.raises(ValueError):
        auth.role_required("superuser")


# ---------------------------------------------------------------------------
# Form UX
# ---------------------------------------------------------------------------

def test_19_field_errors_sit_next_to_their_fields(client):
    response = register(client, name="", email="bad", password="short", branch="", year="9")
    body = response.get_data(as_text=True)
    for field in ("name", "email", "password", "branch", "year"):
        assert f'id="{field}-error"' in body
        # The input points at its own error message.
        start = body.index(f'id="{field}"')
        tag_end = body.index(">", start)
        assert f"{field}-error" in body[start:tag_end]
        # The error comes right after its field, before the next field starts.
        assert body.index(f'id="{field}-error"') > start
    assert body.index('id="name-error"') < body.index('id="email"')
    assert 'value="bad"' in body
    assert 'value="short"' not in body


def test_20_failed_login_keeps_email_but_not_password(client, make_user):
    make_user()
    response = log_in(client, "asha@college.example", "the-wrong-password")
    body = response.get_data(as_text=True)
    assert 'value="asha@college.example"' in body
    assert "the-wrong-password" not in body
    password_tag = body[body.index('id="password"'):]
    assert "value=" not in password_tag[:password_tag.index(">")]


# ---------------------------------------------------------------------------
# Navigation, cookies and pages
# ---------------------------------------------------------------------------

def test_navigation_for_anonymous_visitor(client):
    body = page(client.get("/login"))
    assert 'href="/login"' in body and 'href="/register"' in body
    assert "Log out" not in body
    assert 'href="/">Browse</a>' in body
    assert 'href="/upload"' not in body and 'href="/my-notes"' not in body


# Every navigation item is a real page since Phase 4 (Reports = moderation,
# Subjects = subject administration).
@pytest.mark.parametrize("role, links, soon, hidden", [
    ("student", ["Browse", "Upload", "My Notes"], [], ["Reports", "Subjects"]),
    ("moderator", ["Browse", "Upload", "My Notes", "Reports"], [], ["Subjects"]),
    ("admin", ["Browse", "Upload", "My Notes", "Reports", "Subjects"], [], []),
])
def test_navigation_by_role(client, make_user, role, links, soon, hidden):
    make_user(email=f"{role}@college.example", role=role)
    log_in(client, f"{role}@college.example", "correct-password")
    body = page(client.get("/account"))
    nav = body[body.index('aria-label="Main"'):body.index("</nav>", body.index('aria-label="Main"'))]
    for label in links:
        assert f">{label}</a>" in nav
    for label in soon:
        assert f"{label} <span class=\"soon\">Soon</span>" in nav
    for label in hidden:
        assert label not in nav
    assert 'action="/logout"' in body and 'method="post"' in body


def test_session_cookie_flags(client, make_user):
    make_user()
    response = log_in(client, "asha@college.example", "correct-password")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_root_is_the_browse_page_for_everyone(client, make_user):
    assert client.get("/").status_code == 200
    make_user()
    log_in(client, "asha@college.example", "correct-password")
    response = client.get("/")
    assert response.status_code == 200
    assert "Browse notes" in page(response)


def test_account_page_shows_database_values(client, make_user):
    make_user(role="moderator")
    log_in(client, "asha@college.example", "correct-password")
    body = page(client.get("/account"))
    assert "Asha Kulkarni" in body and "asha@college.example" in body and "Moderator" in body
    assert "scrypt:" not in body


def test_unknown_page_returns_clean_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "Page not found" in page(response)
