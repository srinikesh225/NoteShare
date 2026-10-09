"""Phase 4 tests: ratings, reports, automatic flagging, moderation, warning
bans and subject administration. Every state change goes through the real
routes with real CSRF tokens, against the MySQL test database."""

import html
import re
import threading

import pytest

from conftest import get_csrf_token, log_in, upload_note
from migrate import apply_migrations
from models import Note, Rating, Report, Subject, User, db

PASSWORD = "correct-password"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text_of(response):
    return html.unescape(response.get_data(as_text=True))


def card_titles(response):
    raw = response.get_data(as_text=True)
    return [html.unescape(t) for t in re.findall(r'<h2 class="note-card-title" title="[^"]*">(.*?)</h2>', raw)]


@pytest.fixture
def people(app, make_user):
    """Factory: create a user, sign a fresh client in, return (client, user_id)."""
    def _person(email, role="student", name=None):
        user_id = make_user(email=email, role=role, name=name or email.split("@")[0].title())
        client = app.test_client()
        assert log_in(client, email, PASSWORD).status_code == 302
        return client, user_id
    return _person


def post(client, path, data=None, token_page="/"):
    return client.post(path, data={"csrf_token": get_csrf_token(client, token_page), **(data or {})})


def make_note(app, client, subject_id, title="Graph Algorithms Notes"):
    response = upload_note(client, title, subject_id)
    assert response.status_code == 302, text_of(response)[:500]
    return int(response.headers["Location"].rsplit("/", 1)[1])


def note_row(app, note_id):
    with app.app_context():
        note = db.session.get(Note, note_id)
        db.session.expunge(note)
        return note


def user_row(app, user_id):
    with app.app_context():
        user = db.session.get(User, user_id)
        db.session.expunge(user)
        return user


def reports_for(app, note_id):
    with app.app_context():
        rows = Report.query.filter_by(note_id=note_id).order_by(Report.id).all()
        for row in rows:
            db.session.expunge(row)
        return rows


def ratings_for(app, note_id):
    with app.app_context():
        rows = Rating.query.filter_by(note_id=note_id).all()
        for row in rows:
            db.session.expunge(row)
        return rows


def rate(client, note_id, stars, comment=""):
    return post(client, f"/note/{note_id}/rate", {"stars": stars, "comment": comment})


def report(client, note_id, reason="wrong_subject", details=""):
    return post(client, f"/note/{note_id}/report", {"reason": reason, "details": details})


def moderate(client, note_id, action, **extra):
    return post(client, f"/moderation/note/{note_id}/{action}", extra, token_page="/moderation")


def warn(client, app, note_id):
    uploader_id = note_row(app, note_id).uploader_id
    return moderate(client, note_id, "warn", warnings_seen=user_row(app, uploader_id).warnings)


@pytest.fixture
def world(app, people, subjects):
    """An uploader with one active note, three students and a moderator."""
    uploader, uploader_id = people("uploader@college.example", name="Uma Uploader")
    note_id = make_note(app, uploader, subjects["CS501"])
    a, a_id = people("a@college.example", name="Student A")
    b, b_id = people("b@college.example", name="Student B")
    c, c_id = people("c@college.example", name="Student C")
    mod, mod_id = people("mod@college.example", role="moderator", name="Mona Moderator")
    return {"note": note_id, "uploader": uploader, "uploader_id": uploader_id,
            "a": a, "b": b, "c": c, "ids": {"a": a_id, "b": b_id, "c": c_id},
            "mod": mod, "mod_id": mod_id, "subjects": subjects}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_is_idempotent_and_details_column_exists(app):
    with app.app_context():
        assert apply_migrations(db.engine) == []   # already applied by the fixture
        assert apply_migrations(db.engine) == []
        column = db.session.execute(db.text(
            "SELECT IS_NULLABLE, DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='reports' AND COLUMN_NAME='details'")).one()
        assert tuple(column) == ("YES", "text")


# ---------------------------------------------------------------------------
# Ratings (tests 1-11)
# ---------------------------------------------------------------------------

def test_01_student_can_rate_another_students_note(app, world):
    response = rate(world["a"], world["note"], 4, "Clear diagrams.")
    assert response.status_code == 302
    assert response.headers["Location"] == f"/note/{world['note']}#reviews-heading"
    rows = ratings_for(app, world["note"])
    assert [(r.student_id, r.stars, r.comment) for r in rows] == [(world["ids"]["a"], 4, "Clear diagrams.")]
    body = text_of(world["a"].get(f"/note/{world['note']}"))
    assert "Thanks! Your rating has been saved." in body
    assert "Student A" in body and "Clear diagrams." in body and "from 1 rating" in body


@pytest.mark.parametrize("stars", ["0", "-1", "6", "10", "", "abc", "3.5", " ", "05", "1e0"])
def test_02_to_04_invalid_star_values_are_rejected(app, world, stars):
    response = rate(world["a"], world["note"], stars, "kept comment")
    assert response.status_code == 422
    body = text_of(response)
    assert "Choose a rating from 1 to 5 stars." in body
    assert "kept comment</textarea>" in body
    assert ratings_for(app, world["note"]) == []


def test_04b_missing_stars_field_is_rejected(app, world):
    response = post(world["a"], f"/note/{world['note']}/rate", {"comment": "no stars"})
    assert response.status_code == 422
    assert ratings_for(app, world["note"]) == []


def test_05_student_cannot_rate_own_note(app, world):
    response = rate(world["uploader"], world["note"], 5)
    assert response.status_code == 302
    assert "You cannot rate your own note." in text_of(world["uploader"].get(f"/note/{world['note']}"))
    assert ratings_for(app, world["note"]) == []


def test_06_07_second_rating_updates_instead_of_duplicating(app, world):
    rate(world["a"], world["note"], 3, "Good start")
    response = rate(world["a"], world["note"], 5, "Even better after the update")
    assert response.status_code == 302
    rows = ratings_for(app, world["note"])
    assert len(rows) == 1
    assert (rows[0].stars, rows[0].comment) == (5, "Even better after the update")
    assert note_row(app, world["note"]).avg_rating == 5.0
    body = text_of(world["a"].get(f"/note/{world['note']}"))
    assert "Your rating has been updated." in body
    assert "Even better after the update" in body and "Good start" not in body
    assert "Update your rating" in body


def test_08_update_avg_rating_is_called(app, world, monkeypatch):
    calls = []
    original = Note.update_avg_rating

    def spy(self):
        calls.append(self.id)
        return original(self)

    monkeypatch.setattr(Note, "update_avg_rating", spy)
    rate(world["a"], world["note"], 4)
    rate(world["a"], world["note"], 2)
    assert calls == [world["note"], world["note"]]


def test_09_10_average_after_one_and_many_ratings(app, world, people):
    rate(world["a"], world["note"], 4)
    assert note_row(app, world["note"]).avg_rating == 4.0
    rate(world["b"], world["note"], 5)
    rate(world["c"], world["note"], 2)
    assert note_row(app, world["note"]).avg_rating == 3.67      # (4 + 5 + 2) / 3
    rate(world["c"], world["note"], 5)                          # a changed rating
    assert note_row(app, world["note"]).avg_rating == 4.67
    body = text_of(world["a"].get(f"/note/{world['note']}"))
    assert "4.7" in body and "from 3 ratings" in body
    assert "4.7" in text_of(world["a"].get("/"))                 # homepage card


def test_11_unauthenticated_user_cannot_rate(app, world):
    anonymous = app.test_client()
    token = get_csrf_token(anonymous, "/login")
    response = anonymous.post(f"/note/{world['note']}/rate", data={"csrf_token": token, "stars": "5"})
    assert response.status_code == 302 and response.headers["Location"].startswith("/login")
    assert ratings_for(app, world["note"]) == []


def test_rating_ignores_spoofed_ids_and_escapes_comments(app, world):
    rate_response = post(world["a"], f"/note/{world['note']}/rate",
                         {"stars": "4", "comment": "<script>alert(1)</script>",
                          "student_id": str(world["ids"]["b"]), "note_id": "999999"})
    assert rate_response.status_code == 302
    rows = ratings_for(app, world["note"])
    assert [r.student_id for r in rows] == [world["ids"]["a"]]
    raw = world["a"].get(f"/note/{world['note']}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in raw and "&lt;script&gt;alert(1)&lt;/script&gt;" in raw


def test_rating_comment_length_and_form_values_kept(app, world):
    response = rate(world["a"], world["note"], 4, "x" * 1001)
    assert response.status_code == 422
    assert "Your review must be 1,000 characters or fewer." in text_of(response)
    assert re.search(r'value="4"[^>]* checked', response.get_data(as_text=True))


def test_banned_user_cannot_rate_or_report(app, world):
    token = get_csrf_token(world["a"], "/")
    with app.app_context():
        db.session.get(User, world["ids"]["a"]).is_banned = True
        db.session.commit()
    response = world["a"].post(f"/note/{world['note']}/rate", data={"csrf_token": token, "stars": "5"})
    assert response.status_code == 302 and response.headers["Location"] == "/login"
    assert ratings_for(app, world["note"]) == []


def test_rating_requires_an_active_note(app, world):
    moderate(world["mod"], world["note"], "remove")
    assert rate(world["a"], world["note"], 5).status_code == 404          # hidden from students
    assert rate(world["mod"], world["note"], 5).status_code == 302        # visible, but refused
    assert ratings_for(app, world["note"]) == []


# ---------------------------------------------------------------------------
# Reports (tests 12-22)
# ---------------------------------------------------------------------------

def test_12_16_valid_report_is_saved_open_with_details(app, world):
    response = report(world["a"], world["note"], "copied", "Same as the textbook, page 40.")
    assert response.status_code == 302
    rows = reports_for(app, world["note"])
    assert len(rows) == 1
    row = rows[0]
    assert (row.reporter_id, row.reason, row.details, row.status, row.action_taken) == (
        world["ids"]["a"], "Copied content", "Same as the textbook, page 40.", "open", None)
    body = text_of(world["a"].get(f"/note/{world['note']}"))
    assert "Report submitted." in body
    assert "You reported this note on" in body and "Submit report" not in body


def test_report_form_offers_exactly_the_five_reasons(world):
    raw = world["a"].get(f"/note/{world['note']}").get_data(as_text=True)
    select = raw[raw.index('<select id="reason"'):raw.index("</select>", raw.index('<select id="reason"'))]
    assert re.findall(r'<option value="(\w+)"[^>]*>([^<]+)</option>', select) == [
        ("wrong_subject", "Wrong subject"), ("copied", "Copied content"), ("unreadable", "Unreadable"),
        ("inappropriate", "Inappropriate"), ("other", "Other")]


@pytest.mark.parametrize("reason", ["", "spam", "Wrong subject", "<b>bad</b>", "other_reason"])
def test_13_invalid_reasons_are_rejected(app, world, reason):
    response = report(world["a"], world["note"], reason, "details kept")
    assert response.status_code == 422
    assert "Choose a reason from the list." in text_of(response)
    assert "details kept</textarea>" in text_of(response)
    assert reports_for(app, world["note"]) == []


def test_other_reason_needs_details_and_details_are_limited(app, world):
    response = report(world["a"], world["note"], "other", "")
    assert response.status_code == 422 and "Please describe the problem" in text_of(response)
    response = report(world["a"], world["note"], "unreadable", "x" * 1001)
    assert response.status_code == 422 and "1,000 characters or fewer" in text_of(response)
    assert reports_for(app, world["note"]) == []


def test_14_student_cannot_report_own_note(app, world):
    response = report(world["uploader"], world["note"])
    assert response.status_code == 302
    assert "You cannot report your own note." in text_of(world["uploader"].get(f"/note/{world['note']}"))
    assert reports_for(app, world["note"]) == []
    assert note_row(app, world["note"]).status == "active"


def test_15_duplicate_report_is_rejected(app, world):
    report(world["a"], world["note"], "unreadable")
    response = report(world["a"], world["note"], "copied")
    assert response.status_code == 302
    assert "You have already reported this note." in text_of(world["a"].get(f"/note/{world['note']}"))
    rows = reports_for(app, world["note"])
    assert len(rows) == 1 and rows[0].reason == "Unreadable"


def test_report_ignores_spoofed_reporter_and_status(app, world):
    post(world["a"], f"/note/{world['note']}/report",
         {"reason": "unreadable", "reporter_id": str(world["ids"]["b"]), "status": "resolved"})
    rows = reports_for(app, world["note"])
    assert [(r.reporter_id, r.status) for r in rows] == [(world["ids"]["a"], "open")]


def test_17_18_20_21_third_open_report_flags_the_note(app, world, people):
    report(world["a"], world["note"])
    report(world["b"], world["note"], "unreadable")
    assert note_row(app, world["note"]).status == "active"            # 17: two reports
    assert "Graph Algorithms Notes" in card_titles(world["a"].get("/"))

    response = report(world["c"], world["note"], "copied")
    assert response.status_code == 302 and response.headers["Location"] == "/"   # 18
    assert note_row(app, world["note"]).status == "flagged"
    assert "This note has been flagged for moderator review." in text_of(world["c"].get("/"))

    reader, _ = people("reader@college.example")
    assert "Graph Algorithms Notes" not in card_titles(reader.get("/"))          # 20
    assert reader.get(f"/note/{world['note']}").status_code == 404
    assert reader.get(f"/note/{world['note']}/download", buffered=True).status_code == 404   # 21
    assert note_row(app, world["note"]).download_count == 0
    assert world["uploader"].get(f"/note/{world['note']}").status_code == 200   # uploader still can


def test_19_only_open_reports_count_toward_the_threshold(app, world, people):
    report(world["a"], world["note"])
    report(world["b"], world["note"])
    moderate(world["mod"], world["note"], "dismiss")          # 2 resolved, note active
    report(world["c"], world["note"])
    d, _ = people("d@college.example")
    report(d, world["note"])
    assert note_row(app, world["note"]).status == "active"    # only 2 open (4 total)
    e, _ = people("e@college.example")
    report(e, world["note"])
    assert note_row(app, world["note"]).status == "flagged"   # 3 open
    assert [r.status for r in reports_for(app, world["note"])] == [
        "resolved", "resolved", "open", "open", "open"]


def test_22_removed_note_cannot_be_reactivated_by_a_report(app, world):
    report(world["a"], world["note"])
    moderate(world["mod"], world["note"], "remove")
    assert report(world["b"], world["note"]).status_code == 404     # students can't see it
    response = report(world["mod"], world["note"])                   # moderators can, but...
    assert response.status_code == 302
    assert note_row(app, world["note"]).status == "removed"
    assert len(reports_for(app, world["note"])) == 1


def test_reporter_names_are_not_shown_to_students(app, world):
    report(world["a"], world["note"], "unreadable", "Blurry scan")
    body = text_of(world["b"].get(f"/note/{world['note']}"))
    assert "Student A" not in body and "Blurry scan" not in body
    owner_view = text_of(world["uploader"].get(f"/note/{world['note']}"))
    assert "Student A" not in owner_view and "Blurry scan" not in owner_view


# ---------------------------------------------------------------------------
# Moderation (tests 23-40)
# ---------------------------------------------------------------------------

def test_23_to_25_moderation_access(app, world, people):
    assert world["a"].get("/moderation").status_code == 403                     # 23
    anonymous = app.test_client()
    response = anonymous.get("/moderation")
    assert response.status_code == 302 and response.headers["Location"].startswith("/login")
    assert world["mod"].get("/moderation").status_code == 200                   # 24
    admin, _ = people("admin@college.example", role="admin")
    assert admin.get("/moderation").status_code == 200                          # 25
    assert "No open reports. Everything is clear." in text_of(admin.get("/moderation"))


def test_26_27_flagged_first_and_reports_grouped_by_note(app, world, people):
    subjects = world["subjects"]
    two = world["note"]
    flagged = make_note(app, world["uploader"], subjects["CS502"], "Flagged Note")
    one = make_note(app, world["uploader"], subjects["CS503"], "One Report Note")
    report(world["a"], two)
    report(world["b"], two)
    for student in ("a", "b", "c"):
        report(world[student], flagged, "copied")
    report(world["c"], one, "unreadable")
    assert note_row(app, flagged).status == "flagged"

    raw = world["mod"].get("/moderation").get_data(as_text=True)
    order = re.findall(r'id="mod-title-(\d+)"', raw)
    assert order == [str(flagged), str(two), str(one)]                          # 26
    assert raw.count(f'id="note-{flagged}"') == 1                               # 27: one group
    group = raw[raw.index(f'id="note-{flagged}"'):raw.index(f'id="note-{two}"')]
    assert group.count('class="mod-report"') == 3
    assert "Student A" in group and "Student B" in group and "Student C" in group
    assert "Copied content" in group


def test_28_29_30_dismiss_resolves_reports_and_reactivates(app, world):
    other = make_note(app, world["uploader"], world["subjects"]["CS502"], "Other note")
    report(world["a"], other, "unreadable")                     # must stay open
    for student in ("a", "b", "c"):
        report(world[student], world["note"])
    assert note_row(app, world["note"]).status == "flagged"

    response = moderate(world["mod"], world["note"], "dismiss")
    assert response.status_code == 302 and response.headers["Location"] == "/moderation?page=1"
    assert "Dismissed 3 reports. The note is visible to students again." in text_of(world["mod"].get("/moderation"))
    rows = reports_for(app, world["note"])
    assert [r.status for r in rows] == ["resolved"] * 3                         # 28
    assert all("Dismissed by moderator Mona Moderator" in r.action_taken for r in rows)
    assert note_row(app, world["note"]).status == "active"                      # 29
    assert "Graph Algorithms Notes" in card_titles(world["b"].get("/"))          # 30
    assert [r.status for r in reports_for(app, other)] == ["open"]


def test_31_32_33_remove_hides_note_and_keeps_history(app, world, people):
    rate(world["a"], world["note"], 5)
    report(world["a"], world["note"])
    report(world["b"], world["note"])
    response = moderate(world["mod"], world["note"], "remove")
    assert response.status_code == 302
    note = note_row(app, world["note"])
    assert note.status == "removed"                                             # 31
    rows = reports_for(app, world["note"])
    assert [r.status for r in rows] == ["resolved", "resolved"]                 # 32
    assert all("Note removed by moderator" in r.action_taken for r in rows)
    assert len(ratings_for(app, world["note"])) == 1
    reader, _ = people("reader@college.example")
    assert "Graph Algorithms Notes" not in card_titles(reader.get("/"))          # 33
    assert reader.get(f"/note/{world['note']}").status_code == 404
    assert reader.get(f"/note/{world['note']}/download", buffered=True).status_code == 404
    assert user_row(app, world["uploader_id"]).is_banned is False
    # Dismissing later does not bring a removed note back.
    moderate(world["mod"], world["note"], "dismiss")
    assert note_row(app, world["note"]).status == "removed"


def test_34_35_warnings_increment_and_third_warning_bans(app, world):
    report(world["a"], world["note"])
    for expected in (1, 2):
        assert warn(world["mod"], app, world["note"]).status_code == 302
        uploader = user_row(app, world["uploader_id"])
        assert (uploader.warnings, uploader.is_banned) == (expected, False)        # 34
    assert f"Warning count: 2 of 3." in text_of(world["mod"].get("/moderation"))

    warn(world["mod"], app, world["note"])
    uploader = user_row(app, world["uploader_id"])
    assert (uploader.warnings, uploader.is_banned) == (3, True)                  # 35
    assert "has been suspended automatically" in text_of(world["mod"].get("/moderation"))
    assert reports_for(app, world["note"])[0].status == "open"   # warning does not close reports
    assert "warned (3 of 3) and automatically suspended" in reports_for(app, world["note"])[0].action_taken


def test_repeated_warning_form_does_not_double_count(app, world):
    seen = user_row(app, world["uploader_id"]).warnings
    token = get_csrf_token(world["mod"], "/moderation")
    data = {"csrf_token": token, "warnings_seen": seen}
    path = f"/moderation/note/{world['note']}/warn"
    assert world["mod"].post(path, data=data).status_code == 302
    assert world["mod"].post(path, data=data).status_code == 302     # double click / resubmit
    assert user_row(app, world["uploader_id"]).warnings == 1
    assert "no warning was added" in text_of(world["mod"].get("/moderation"))
    assert world["mod"].post(path, data={"csrf_token": token}).status_code == 302   # no count sent
    assert user_row(app, world["uploader_id"]).warnings == 1


def test_36_37_direct_ban_blocks_login_and_existing_sessions(app, world):
    response = moderate(world["mod"], world["note"], "ban")
    assert response.status_code == 302
    uploader = user_row(app, world["uploader_id"])
    assert uploader.is_banned is True                                           # 36
    assert uploader.warnings == 0 and uploader.email == "uploader@college.example"
    assert note_row(app, world["note"]).status == "active"   # notes are kept
    assert "Uma Uploader has been suspended and can no longer log in." in text_of(world["mod"].get("/moderation"))

    response = world["uploader"].get("/my-notes")                               # 37: old session
    assert response.status_code == 302 and response.headers["Location"] == "/login"
    fresh = app.test_client()
    response = log_in(fresh, "uploader@college.example", PASSWORD)
    assert response.status_code == 403 and "Your account has been suspended." in text_of(response)


def test_moderator_cannot_warn_or_ban_an_admin(app, people, subjects, world):
    admin, admin_id = people("boss@college.example", role="admin")
    admin_note = make_note(app, admin, subjects["CS601"], "Admin note")
    moderate(world["mod"], admin_note, "ban")
    warn(world["mod"], app, admin_note)
    assert (user_row(app, admin_id).is_banned, user_row(app, admin_id).warnings) == (False, 0)
    assert "Only an administrator can warn or suspend this admin." in text_of(world["mod"].get("/moderation"))


def test_admin_has_moderator_powers(app, world, people):
    admin, _ = people("admin@college.example", role="admin")
    for student in ("a", "b", "c"):
        report(world[student], world["note"])
    assert moderate(admin, world["note"], "dismiss").status_code == 302
    assert note_row(app, world["note"]).status == "active"


@pytest.mark.parametrize("action", ["dismiss", "remove", "warn", "ban"])
def test_38_students_cannot_trigger_moderation_actions(app, world, action):
    for student in ("a", "b", "c"):
        report(world[student], world["note"])
    response = post(world["a"], f"/moderation/note/{world['note']}/{action}", {"warnings_seen": 0})
    assert response.status_code == 403
    assert note_row(app, world["note"]).status == "flagged"
    assert [r.status for r in reports_for(app, world["note"])] == ["open"] * 3
    uploader = user_row(app, world["uploader_id"])
    assert (uploader.warnings, uploader.is_banned) == (0, False)


@pytest.mark.parametrize("action", ["dismiss", "remove", "warn", "ban"])
def test_39_40_get_and_missing_csrf_cannot_change_anything(app, world, action):
    report(world["a"], world["note"])
    path = f"/moderation/note/{world['note']}/{action}"
    assert world["mod"].get(path).status_code == 405                            # 39
    assert world["mod"].post(path, data={"warnings_seen": 0}).status_code == 400  # 40
    assert world["mod"].post(path, data={"csrf_token": "forged", "warnings_seen": 0}).status_code == 400
    assert note_row(app, world["note"]).status == "active"
    assert reports_for(app, world["note"])[0].status == "open"
    uploader = user_row(app, world["uploader_id"])
    assert (uploader.warnings, uploader.is_banned) == (0, False)


def test_moderation_action_on_missing_note_returns_404(world):
    assert moderate(world["mod"], 999999, "dismiss").status_code == 404


def test_students_do_not_see_moderation_controls(app, world):
    for student in ("a", "b"):
        report(world[student], world["note"])
    body = world["c"].get(f"/note/{world['note']}").get_data(as_text=True)
    assert "/moderation" not in body
    assert "open report" in world["mod"].get(f"/note/{world['note']}").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Subject administration (tests 41-50)
# ---------------------------------------------------------------------------

@pytest.fixture
def admin(people):
    client, _ = people("admin@college.example", role="admin")
    return client


def subject_by_code(app, code):
    with app.app_context():
        subject = Subject.query.filter_by(code=code).first()
        if subject is not None:
            db.session.expunge(subject)
        return subject


def add_subject(client, code, name, semester):
    return post(client, "/admin/subjects/add", {"code": code, "name": name, "semester": semester},
                token_page="/admin/subjects/add")


def test_41_42_only_admins_can_manage_subjects(app, people, subjects):
    student, _ = people("s@college.example")
    moderator, _ = people("m@college.example", role="moderator")
    target = subjects["CS501"]
    for client in (student, moderator):
        assert client.get("/admin/subjects").status_code == 403
        assert client.get("/admin/subjects/add").status_code == 403
        assert client.get(f"/admin/subjects/{target}/edit").status_code == 403
        token = get_csrf_token(client, "/")
        assert client.post("/admin/subjects/add", data={"csrf_token": token, "code": "X1",
                                                        "name": "X", "semester": "1"}).status_code == 403
        assert client.post(f"/admin/subjects/{target}/delete", data={"csrf_token": token}).status_code == 403
    response = app.test_client().get("/admin/subjects")
    assert response.status_code == 302 and response.headers["Location"].startswith("/login")
    assert subject_by_code(app, "X1") is None and subject_by_code(app, "CS501") is not None


def test_43_admin_can_add_subject(app, admin, subjects):
    response = add_subject(admin, "  cs 701 ", "  Compiler   Design ", "7")
    assert response.status_code == 302 and response.headers["Location"] == "/admin/subjects"
    subject = subject_by_code(app, "CS 701")
    assert (subject.name, subject.semester) == ("Compiler Design", 7)
    body = text_of(admin.get("/admin/subjects"))
    assert "Subject CS 701 added." in body and "Compiler Design" in body


@pytest.mark.parametrize("code, name, semester, field_message", [
    ("CS501", "Duplicate", "5", "A subject with the code CS501 already exists."),
    ("cs501", "Duplicate lower case", "5", "A subject with the code CS501 already exists."),
    ("", "No code", "5", "Please enter a subject code."),
    ("X" * 21, "Long code", "5", "Code must be 20 characters or fewer."),
    ("CS<5>", "Bad characters", "5", "Use letters, numbers, spaces or hyphens"),
    ("CS801", "", "8", "Please enter the subject name."),
    ("CS801", "N" * 151, "8", "Name must be 150 characters or fewer."),
    ("CS801", "Bad semester", "0", "Choose a semester from 1 to 8."),
    ("CS801", "Bad semester", "9", "Choose a semester from 1 to 8."),
    ("CS801", "Bad semester", "abc", "Choose a semester from 1 to 8."),
])
def test_44_invalid_or_duplicate_subjects_are_rejected(app, admin, subjects, code, name, semester, field_message):
    response = add_subject(admin, code, name, semester)
    assert response.status_code == 422
    assert field_message in text_of(response)
    with app.app_context():
        assert Subject.query.count() == 6


def test_add_subject_form_keeps_values_after_error(admin, subjects):
    raw = add_subject(admin, "CS501", "Kept name", "4").get_data(as_text=True)
    assert 'value="CS501"' in raw and 'value="Kept name"' in raw and '<option value="4" selected>' in raw


def test_45_46_admin_can_edit_subject_without_touching_notes(app, admin, people, subjects):
    uploader, uploader_id = people("u@college.example")
    note_id = make_note(app, uploader, subjects["CS501"])
    target = subjects["CS501"]
    # Saving with the same code is not treated as a duplicate of itself.
    response = post(admin, f"/admin/subjects/{target}/edit",
                    {"code": "CS501", "name": "Algorithms (renamed)", "semester": "5"},
                    token_page=f"/admin/subjects/{target}/edit")
    assert response.status_code == 302
    # Changing to another subject's code is refused.
    response = post(admin, f"/admin/subjects/{target}/edit",
                    {"code": "CS502", "name": "Clash", "semester": "5"}, token_page=f"/admin/subjects/{target}/edit")
    assert response.status_code == 422 and "A subject with the code CS502 already exists." in text_of(response)
    # A real change of code and semester.
    response = post(admin, f"/admin/subjects/{target}/edit",
                    {"code": "CS511", "name": "Advanced Algorithms", "semester": "6"},
                    token_page=f"/admin/subjects/{target}/edit")
    assert response.status_code == 302
    with app.app_context():
        subject = db.session.get(Subject, target)
        assert (subject.code, subject.name, subject.semester) == ("CS511", "Advanced Algorithms", 6)
        note = db.session.get(Note, note_id)
        assert note.subject_id == target and note.uploader_id == uploader_id and note.status == "active"
    assert "CS511" in text_of(uploader.get(f"/note/{note_id}"))


def test_47_subject_with_notes_cannot_be_deleted(app, admin, people, subjects):
    uploader, _ = people("u@college.example")
    note_id = make_note(app, uploader, subjects["CS501"])
    response = post(admin, f"/admin/subjects/{subjects['CS501']}/delete", token_page="/admin/subjects")
    assert response.status_code == 302
    assert "This subject cannot be deleted because notes are associated with it." in text_of(admin.get("/admin/subjects"))
    assert subject_by_code(app, "CS501") is not None
    assert note_row(app, note_id).subject_id == subjects["CS501"]


def test_48_subject_without_notes_can_be_deleted(app, admin, subjects):
    response = post(admin, f"/admin/subjects/{subjects['CS603']}/delete", token_page="/admin/subjects")
    assert response.status_code == 302
    assert subject_by_code(app, "CS603") is None
    assert "Subject CS603 deleted." in text_of(admin.get("/admin/subjects"))


def test_49_50_delete_needs_post_and_csrf(app, admin, subjects):
    path = f"/admin/subjects/{subjects['CS603']}/delete"
    assert admin.get(path).status_code == 405                                    # 49
    assert admin.post(path).status_code == 400                                   # 50
    assert admin.post(f"/admin/subjects/{subjects['CS603']}/edit",
                      data={"code": "ZZ1", "name": "x", "semester": "1"}).status_code == 400
    assert subject_by_code(app, "CS603") is not None


def test_subject_list_shows_counts_and_empty_state(app, admin, people, subjects):
    uploader, _ = people("u@college.example")
    make_note(app, uploader, subjects["CS501"])
    raw = admin.get("/admin/subjects").get_data(as_text=True)
    row = raw[raw.index(">CS501<"):raw.index("</tr>", raw.index(">CS501<"))]
    assert f'href="/?subject={subjects["CS501"]}">1</a>' in row and "In use" in row
    with app.app_context():
        db.session.execute(db.text("DELETE FROM notes"))
        db.session.execute(db.text("DELETE FROM subjects"))
        db.session.commit()
    assert "No subjects found." in text_of(admin.get("/admin/subjects"))


def test_missing_subject_returns_404(admin):
    assert admin.get("/admin/subjects/999999/edit").status_code == 404
    assert post(admin, "/admin/subjects/999999/delete", token_page="/admin/subjects").status_code == 404


# ---------------------------------------------------------------------------
# Required end-to-end workflow: three students report one note
# ---------------------------------------------------------------------------

def test_e2e_three_students_report_then_moderator_dismisses(app, world, people):
    note_id = world["note"]
    other = make_note(app, world["uploader"], world["subjects"]["CS502"], "Unrelated Note")
    report(world["a"], other, "unreadable")   # an unrelated open report, ranked lower

    def open_reports():
        return [r for r in reports_for(app, note_id) if r.status == "open"]

    # Step 1
    assert report(world["a"], note_id, "wrong_subject", "This is CN, not DAA.").status_code == 302
    assert len(open_reports()) == 1 and note_row(app, note_id).status == "active"
    # Step 2
    assert report(world["b"], note_id, "copied").status_code == 302
    assert len(open_reports()) == 2 and note_row(app, note_id).status == "active"
    # Step 3
    assert report(world["c"], note_id, "unreadable", "Pages 3-5 are blank.").status_code == 302
    assert len(open_reports()) == 3 and note_row(app, note_id).status == "flagged"
    reader, _ = people("reader@college.example")
    assert "Graph Algorithms Notes" not in card_titles(reader.get("/"))
    assert reader.get(f"/note/{note_id}/download", buffered=True).status_code == 404

    # Step 4
    raw = world["mod"].get("/moderation").get_data(as_text=True)
    assert re.findall(r'id="mod-title-(\d+)"', raw)[0] == str(note_id)
    group = raw[raw.index(f'id="note-{note_id}"'):raw.index(f'id="note-{other}"')]
    assert group.count('class="mod-report"') == 3
    for text in ("Wrong subject", "Copied content", "Unreadable", "This is CN, not DAA.", "Pages 3-5 are blank."):
        assert text in html.unescape(group)

    # Step 5
    assert moderate(world["mod"], note_id, "dismiss").status_code == 302
    assert note_row(app, note_id).status == "active"
    assert "Graph Algorithms Notes" in card_titles(reader.get("/"))
    raw = world["mod"].get("/moderation").get_data(as_text=True)
    assert f'id="note-{note_id}"' not in raw and f'id="note-{other}"' in raw

    # Step 6: database state
    rows = reports_for(app, note_id)
    assert len(rows) == 3 and {r.status for r in rows} == {"resolved"}
    assert {r.reporter_id for r in rows} == set(world["ids"].values())
    assert [r.status for r in reports_for(app, other)] == ["open"]
    # The same students cannot report again (one report per student per note).
    report(world["a"], note_id)
    assert len(reports_for(app, note_id)) == 3


# ---------------------------------------------------------------------------
# Concurrency: simultaneous reports and ratings
# ---------------------------------------------------------------------------

def _run_together(clients, action):
    barrier = threading.Barrier(len(clients))
    tokens = [get_csrf_token(c, "/") for c in clients]
    results = [None] * len(clients)

    def worker(index):
        barrier.wait()
        results[index] = action(clients[index], tokens[index]).status_code

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(clients))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def test_simultaneous_reports_still_flag_the_note(app, world, people):
    clients = [people(f"r{i}@college.example")[0] for i in range(6)]
    note_id = world["note"]
    results = _run_together(clients, lambda c, t: c.post(f"/note/{note_id}/report",
                                                         data={"csrf_token": t, "reason": "copied"}))
    # Reports are processed one at a time (the note row is locked). The first
    # three are accepted and flag the note; after that the note is hidden from
    # ordinary students, so the remaining three get 404 and add nothing.
    assert sorted(results) == [302, 302, 302, 404, 404, 404]
    rows = reports_for(app, note_id)
    assert len(rows) == 3 and {r.status for r in rows} == {"open"}
    assert note_row(app, note_id).status == "flagged"


def test_simultaneous_ratings_keep_the_average_exact(app, world, people):
    clients = [people(f"q{i}@college.example")[0] for i in range(6)]
    stars = [1, 2, 3, 4, 5, 5]
    note_id = world["note"]
    results = _run_together(clients, lambda c, t: c.post(
        f"/note/{note_id}/rate", data={"csrf_token": t, "stars": stars[clients.index(c)]}))
    assert results == [302] * 6
    assert len(ratings_for(app, note_id)) == 6
    assert note_row(app, note_id).avg_rating == round(sum(stars) / 6, 2)
