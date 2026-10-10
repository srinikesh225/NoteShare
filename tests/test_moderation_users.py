"""Moderator user management: /moderation/users, unban and reset warnings."""

import html
import re

import pytest

from models import User, db
from tests.conftest import get_csrf_token, log_in, upload_note

PASSWORD = "correct-password"


def text_of(response):
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def person(app, make_user):
    def _person(email, role="student", name=None, warnings=0, is_banned=False, sign_in=True):
        user_id = make_user(email=email, role=role, name=name or email.split("@")[0].title(),
                            is_banned=is_banned)
        if warnings:
            with app.app_context():
                db.session.get(User, user_id).warnings = warnings
                db.session.commit()
        client = app.test_client()
        if sign_in and not is_banned:
            assert log_in(client, email, PASSWORD).status_code == 302
        client.user_id = user_id
        return client
    return _person


@pytest.fixture
def moderator(person):
    return person("mod@college.example", role="moderator", name="Mona Moderator")


def user_row(app, user_id):
    with app.app_context():
        user = db.session.get(User, user_id)
        db.session.expunge(user)
        return user


def act(client, user_id, action, q="", page=1):
    token = get_csrf_token(client, "/moderation/users")
    return client.post(f"/moderation/users/{user_id}/{action}",
                       data={"csrf_token": token, "q": q, "page": page})


def table_row(raw, user_id):
    start = raw.index(f'id="user-{user_id}"')
    return raw[start:raw.index("</tr>", start)]


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------

def test_moderator_can_unban_a_student(app, person, moderator):
    banned = person("banned@college.example", name="Bina Banned", warnings=3, is_banned=True)
    response = act(moderator, banned.user_id, "unban")
    assert response.status_code == 302 and response.headers["Location"] == "/moderation/users?page=1"
    assert "Bina Banned has been unbanned and can log in again." in text_of(moderator.get("/moderation/users"))
    user = user_row(app, banned.user_id)
    assert user.is_banned is False
    assert user.warnings == 3, "unbanning must not change the warning count"


def test_moderator_can_reset_warnings(app, person, moderator):
    warned = person("warned@college.example", name="Wasim Warned", warnings=2)
    response = act(moderator, warned.user_id, "reset-warnings")
    assert response.status_code == 302
    assert "Wasim Warned's warnings have been reset to 0." in text_of(moderator.get("/moderation/users"))
    user = user_row(app, warned.user_id)
    assert (user.warnings, user.is_banned) == (0, False)


def test_reset_warnings_does_not_unban(app, person, moderator):
    banned = person("banned@college.example", warnings=3, is_banned=True)
    act(moderator, banned.user_id, "reset-warnings")
    user = user_row(app, banned.user_id)
    assert (user.warnings, user.is_banned) == (0, True)


def test_student_cannot_open_moderation_users(app, person):
    target = person("target@college.example", warnings=2, is_banned=True, name="Tara Target")
    student = person("student@college.example")
    response = student.get("/moderation/users")
    assert response.status_code == 403
    assert "Access denied" in text_of(response) and "Tara Target" not in text_of(response)
    # Posting the actions directly is refused too, and nothing changes.
    token = get_csrf_token(student, "/")
    for action in ("unban", "reset-warnings"):
        assert student.post(f"/moderation/users/{target.user_id}/{action}",
                            data={"csrf_token": token}).status_code == 403
    user = user_row(app, target.user_id)
    assert (user.warnings, user.is_banned) == (2, True)
    # Signed-out visitors are sent to log in.
    response = app.test_client().get("/moderation/users")
    assert response.status_code == 302 and response.headers["Location"].startswith("/login")


def test_unbanned_student_can_log_in_again(app, person, moderator):
    banned = person("banned@college.example", name="Bina Banned", is_banned=True)
    blocked = log_in(app.test_client(), "banned@college.example", PASSWORD)
    assert blocked.status_code == 403 and "Your account has been suspended." in text_of(blocked)

    act(moderator, banned.user_id, "unban")
    fresh = app.test_client()
    response = log_in(fresh, "banned@college.example", PASSWORD)
    assert response.status_code == 302 and response.headers["Location"] == "/"
    assert fresh.get("/my-notes").status_code == 200


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------

def test_admin_can_open_users_page(person):
    admin = person("admin@college.example", role="admin")
    assert admin.get("/moderation/users").status_code == 200


def test_users_page_lists_students_with_details(app, person, moderator, subjects):
    uploader = person("ananya@college.example", name="Ananya Reddy")
    upload_note(uploader, "One", subjects["CS501"])
    upload_note(uploader, "Two", subjects["CS502"])
    person("kiran@college.example", name="Kiran Banned", warnings=3, is_banned=True)
    person("other-mod@college.example", role="moderator", name="Other Moderator")
    person("boss@college.example", role="admin", name="Boss Admin")

    raw = moderator.get("/moderation/users").get_data(as_text=True)
    listed = {html.unescape(n) for n in re.findall(r'<th scope="row" data-label="Name">(.*?)</th>', raw)}
    assert listed == {"Ananya Reddy", "Kiran Banned"}, "only students are listed"

    row = html.unescape(table_row(raw, uploader.user_id))
    assert "ananya@college.example" in row and "0 of 3" in row and ">Active<" in row
    assert re.search(r'data-label="Uploads">2<', row)
    assert "No action needed" in row and "Unban" not in row and "Reset warnings" not in row


def test_buttons_only_show_when_they_apply(app, person, moderator):
    warned = person("warned@college.example", warnings=1)
    banned = person("banned@college.example", is_banned=True)
    both = person("both@college.example", warnings=3, is_banned=True)
    raw = moderator.get("/moderation/users").get_data(as_text=True)

    row = table_row(raw, warned.user_id)
    assert "Reset warnings" in row and "Unban" not in row
    row = table_row(raw, banned.user_id)
    assert "Unban" in row and "Reset warnings" not in row and ">Banned<" in row and "status--banned" in row
    row = html.unescape(table_row(raw, both.user_id))
    assert "Unban" in row and "Reset warnings" in row
    assert "their next warning will suspend them again" in row      # unban hint
    assert "This does not unban them." in row                      # reset hint
    # Each action sits behind a confirmation step with its own "Yes" button.
    assert row.count("<details") == 2 and "Yes, unban" in row and "Yes, reset warnings" in row


@pytest.mark.parametrize("query, expected", [
    ("ananya", {"Ananya Reddy"}),             # by name, case-insensitive
    ("KIRAN@", {"Kiran Kumar"}),              # by email
    ("college.example", {"Ananya Reddy", "Kiran Kumar"}),
    ("nobody", set()),
    ("%", set()),                             # wildcards are literal
])
def test_search_by_name_or_email(person, moderator, query, expected):
    person("ananya@college.example", name="Ananya Reddy")
    person("kiran@college.example", name="Kiran Kumar")
    raw = moderator.get("/moderation/users", query_string={"q": query}).get_data(as_text=True)
    names = {html.unescape(n) for n in re.findall(r'<th scope="row" data-label="Name">(.*?)</th>', raw)}
    assert names == expected
    assert f'value="{html.escape(query)}"' in raw or query == "%"
    if not expected:
        assert "No students match" in html.unescape(raw)


def test_actions_keep_the_search_and_page(person, moderator):
    banned = person("banned@college.example", name="Bina", is_banned=True)
    response = act(moderator, banned.user_id, "unban", q="bina", page=1)
    assert response.headers["Location"] == "/moderation/users?q=bina&page=1"


def test_repeating_an_action_is_harmless(app, person, moderator):
    student = person("s@college.example", name="Sam", warnings=1)
    act(moderator, student.user_id, "unban")             # not banned
    assert "Sam is not suspended." in text_of(moderator.get("/moderation/users"))
    act(moderator, student.user_id, "reset-warnings")
    act(moderator, student.user_id, "reset-warnings")    # double submit
    assert "Sam has no warnings." in text_of(moderator.get("/moderation/users"))
    assert user_row(app, student.user_id).warnings == 0


def test_staff_accounts_cannot_be_changed_here(app, person, moderator):
    other = person("other-mod@college.example", role="moderator", warnings=2, is_banned=True, sign_in=False)
    for action in ("unban", "reset-warnings"):
        assert act(moderator, other.user_id, action).status_code == 404
    user = user_row(app, other.user_id)
    assert (user.warnings, user.is_banned) == (2, True)
    assert act(moderator, 999999, "unban").status_code == 404


@pytest.mark.parametrize("action", ["unban", "reset-warnings"])
def test_actions_need_post_and_csrf(app, person, moderator, action):
    student = person("s@college.example", warnings=2, is_banned=True)
    path = f"/moderation/users/{student.user_id}/{action}"
    assert moderator.get(path).status_code == 405
    assert moderator.post(path).status_code == 400
    assert moderator.post(path, data={"csrf_token": "forged"}).status_code == 400
    user = user_row(app, student.user_id)
    assert (user.warnings, user.is_banned) == (2, True)


def test_users_link_in_navigation(person, moderator):
    raw = moderator.get("/moderation/users").get_data(as_text=True)
    assert 'href="/moderation/users" aria-current="page">Users</a>' in raw
    student = person("s@college.example")
    assert 'href="/moderation/users"' not in student.get("/").get_data(as_text=True)


def test_users_page_empty_state(moderator):
    assert "No student accounts yet." in text_of(moderator.get("/moderation/users"))


# ---------------------------------------------------------------------------
# The manual walkthrough from the README, automated end to end
# ---------------------------------------------------------------------------

def test_e2e_report_warn_ban_then_unban_and_reset(app, person, moderator, subjects):
    """Upload -> two reports -> warn -> ban -> Users page -> reset -> unban -> log in."""
    student1 = person("student1@college.example", name="Ananya Reddy")
    student2 = person("student2@college.example", name="Karthik Menon")
    student3 = person("student3@college.example", name="Sneha Patil")

    # 1. Student 1 uploads a note.
    response = upload_note(student1, "Graph Algorithms Notes", subjects["CS501"])
    assert response.status_code == 302
    note_id = int(response.headers["Location"].rsplit("/", 1)[1])

    # 2. Two other students report it (two reports: not yet flagged).
    for reporter in (student2, student3):
        token = get_csrf_token(reporter, f"/note/{note_id}")
        assert reporter.post(f"/note/{note_id}/report",
                             data={"csrf_token": token, "reason": "unreadable"}).status_code == 302

    # 3. The moderator sees the note on the Reports page, warns, then bans the uploader.
    dashboard = moderator.get("/moderation").get_data(as_text=True)
    assert f'id="note-{note_id}"' in dashboard
    token = get_csrf_token(moderator, "/moderation")
    moderator.post(f"/moderation/note/{note_id}/warn", data={"csrf_token": token, "warnings_seen": 0})
    assert "Warning count: 1 of 3." in text_of(moderator.get("/moderation"))
    token = get_csrf_token(moderator, "/moderation")
    moderator.post(f"/moderation/note/{note_id}/ban", data={"csrf_token": token})
    assert "Ananya Reddy has been suspended" in text_of(moderator.get("/moderation"))

    # 4. The Users page now shows Student 1 as banned with 1 warning and both buttons.
    raw = moderator.get("/moderation/users").get_data(as_text=True)
    row = html.unescape(table_row(raw, student1.user_id))
    assert "1 of 3" in row and ">Banned<" in row
    assert "Unban" in row and "Reset warnings" in row
    other = table_row(raw, student2.user_id)
    assert "No action needed" in other

    # 5. Student 1 is locked out: the old session ends and a fresh login is refused.
    assert student1.get("/my-notes").headers["Location"] == "/login"
    refused = log_in(app.test_client(), "student1@college.example", PASSWORD)
    assert refused.status_code == 403

    # 6. Reset warnings first: warnings 0, still banned.
    act(moderator, student1.user_id, "reset-warnings")
    user = user_row(app, student1.user_id)
    assert (user.warnings, user.is_banned) == (0, True)
    row = html.unescape(table_row(moderator.get("/moderation/users").get_data(as_text=True), student1.user_id))
    assert "0 of 3" in row and "Unban" in row and "Reset warnings" not in row

    # 7. Then unban: active again, no actions left on the row.
    act(moderator, student1.user_id, "unban")
    user = user_row(app, student1.user_id)
    assert (user.warnings, user.is_banned) == (0, False)
    row = html.unescape(table_row(moderator.get("/moderation/users").get_data(as_text=True), student1.user_id))
    assert ">Active<" in row and "No action needed" in row

    # 8. Student 1 logs in again and their note and account are intact.
    again = app.test_client()
    assert log_in(again, "student1@college.example", PASSWORD).headers["Location"] == "/"
    assert "Graph Algorithms Notes" in text_of(again.get("/my-notes"))
