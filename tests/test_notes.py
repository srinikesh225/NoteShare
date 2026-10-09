"""Phase 3 tests: upload, browse/search/filter/sort/paginate, details, download,
My Notes and delete. Run against the MySQL test database and a temporary
upload folder (see conftest.py)."""

import html
import io
import os
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.exc import SQLAlchemyError

from conftest import (get_csrf_token, log_in, make_docx, make_pdf, make_png, make_pptx,
                      upload_note)
from models import Note, Rating, Report, User, db

UUID_NAME = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|pptx|jpg|png)$")
PASSWORD = "correct-password"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text_of(response):
    return html.unescape(response.get_data(as_text=True))


def card_titles(response):
    raw = response.get_data(as_text=True)
    return [html.unescape(t) for t in re.findall(r'<h2 class="note-card-title" title="[^"]*">(.*?)</h2>', raw)]


def link_query(response, rel):
    match = re.search(rf'rel="{rel}" href="([^"]+)"', response.get_data(as_text=True))
    assert match, f"no {rel} link"
    parts = urlsplit(html.unescape(match.group(1)))
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


def sign_in(client, make_user, email="asha@college.example", role="student", name="Asha Kulkarni"):
    user_id = make_user(email=email, role=role, name=name)
    log_in(client, email, PASSWORD)
    return user_id


def note_by_title(app, title):
    with app.app_context():
        note = Note.query.filter_by(title=title).one()
        db.session.expunge(note)
        return note


def set_note(app, title, **fields):
    with app.app_context():
        note = Note.query.filter_by(title=title).one()
        for key, value in fields.items():
            setattr(note, key, value)
        db.session.commit()


def stored_files(app):
    return sorted(os.listdir(app.config["UPLOAD_FOLDER"]))


def upload_ok(client, title, subject_id, **kwargs):
    response = upload_note(client, title, subject_id, **kwargs)
    assert response.status_code == 302, text_of(response)[:2000]
    return response


@pytest.fixture
def student(client, make_user):
    return sign_in(client, make_user)


# ---------------------------------------------------------------------------
# Upload (tests 1-13)
# ---------------------------------------------------------------------------

def test_01_upload_requires_login(app, client, subjects):
    response = client.get("/upload")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login?next=/upload"

    token = get_csrf_token(client, "/login")
    response = client.post("/upload", data={"csrf_token": token, "title": "x",
                                            "subject_id": subjects["CS501"],
                                            "file": (io.BytesIO(make_pdf()), "x.pdf")},
                           content_type="multipart/form-data")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    with app.app_context():
        assert Note.query.count() == 0
    assert stored_files(app) == []


def test_02_to_08_valid_pdf_upload(app, client, make_user, subjects):
    user_id = sign_in(client, make_user)
    pdf = make_pdf("Graph Algorithms")
    response = upload_note(client, "Graph Algorithms Notes", subjects["CS501"],
                           filename="My Graph Notes (final).pdf", data=pdf,
                           description="BFS, DFS and shortest paths.")
    assert response.status_code == 302                                   # 2

    note = note_by_title(app, "Graph Algorithms Notes")
    assert response.headers["Location"] == f"/note/{note.id}"
    assert note.file_path != "My Graph Notes (final).pdf"                 # 3
    assert UUID_NAME.match(note.file_path)                                # 4
    assert note.file_path.endswith(".pdf")
    assert note.subject_id == subjects["CS501"]                           # 5
    assert note.uploader_id == user_id                                    # 6
    assert note.status == "active"                                        # 7
    assert note.download_count == 0                                       # 8
    assert note.avg_rating == 0
    assert note.description == "BFS, DFS and shortest paths."
    assert note.upload_date is not None

    assert stored_files(app) == [note.file_path]
    with open(os.path.join(app.config["UPLOAD_FOLDER"], note.file_path), "rb") as fh:
        assert fh.read() == pdf

    assert "Your note has been uploaded." in text_of(client.get(f"/note/{note.id}"))


def test_upload_ignores_submitted_uploader_and_status(app, client, make_user, subjects):
    other_id = make_user(email="other@college.example")
    user_id = sign_in(client, make_user)
    upload_ok(client, "Mine", subjects["CS501"], uploader_id=str(other_id),
              status="removed", download_count="500")
    note = note_by_title(app, "Mine")
    assert note.uploader_id == user_id
    assert note.status == "active" and note.download_count == 0


@pytest.mark.parametrize("filename", ["notes.exe", "notes.txt", "notes.html", "notes.jpeg",
                                      "notes", "notes.pdf.exe", "notes.svg"])
def test_09_unsupported_extensions_rejected(app, client, student, subjects, filename):
    response = upload_note(client, "Bad type", subjects["CS501"], filename=filename)
    assert response.status_code == 422
    assert "This file type isn't allowed." in text_of(response)
    with app.app_context():
        assert Note.query.count() == 0
    assert stored_files(app) == []


@pytest.mark.parametrize("filename, data", [
    ("renamed.pdf", b"MZ\x90\x00 this is really an exe"),
    ("renamed.docx", make_pdf()),
    ("renamed.pptx", make_docx()),       # a Word file renamed to .pptx
    ("renamed.png", b"<html><script>alert(1)</script></html>"),
    ("renamed.jpg", make_png()),
])
def test_09b_file_content_must_match_extension(app, client, student, subjects, filename, data):
    response = upload_note(client, "Mismatch", subjects["CS501"], filename=filename, data=data)
    assert response.status_code == 422
    assert "doesn't look like a valid" in text_of(response)
    assert stored_files(app) == []


def test_upper_case_extension_is_accepted_and_normalised(app, client, student, subjects):
    upload_ok(client, "Caps", subjects["CS501"], filename="SCAN.PDF")
    assert note_by_title(app, "Caps").file_path.endswith(".pdf")


def test_10_missing_file_rejected(app, client, student, subjects):
    token = get_csrf_token(client, "/upload")
    response = client.post("/upload", data={"csrf_token": token, "title": "No file",
                                            "subject_id": subjects["CS501"]},
                           content_type="multipart/form-data")
    assert response.status_code == 422
    assert "Please choose a file to upload." in text_of(response)

    response = upload_note(client, "Empty name", subjects["CS501"], filename="", data=b"")
    assert "Please choose a file to upload." in text_of(response)

    response = upload_note(client, "Empty file", subjects["CS501"], filename="empty.pdf", data=b"")
    assert "The selected file is empty." in text_of(response)
    with app.app_context():
        assert Note.query.count() == 0


def test_11_oversized_upload_rejected(app, client, student, subjects):
    too_big = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024)
    response = upload_note(client, "Huge", subjects["CS501"], filename="huge.pdf", data=too_big)
    assert response.status_code == 413
    assert "This file is larger than the 10 MiB limit." in text_of(response)
    with app.app_context():
        assert Note.query.count() == 0
    assert stored_files(app) == []


def test_upload_just_under_the_limit_is_accepted(app, client, student, subjects):
    almost = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 - 64 * 1024)
    upload_ok(client, "Big but allowed", subjects["CS501"], filename="big.pdf", data=almost)
    assert len(stored_files(app)) == 1


def test_max_content_length_is_10_mib(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 10 * 1024 * 1024
    assert app.config["ALLOWED_EXTENSIONS"] == {"pdf", "docx", "pptx", "jpg", "png"}


@pytest.mark.parametrize("subject_value, message", [
    ("999999", "Choose a subject from the list."),
    ("abc", "Choose a subject from the list."),
    ("-1", "Choose a subject from the list."),
    ("", "Please choose a subject."),
])
def test_12_invalid_subject_rejected(app, client, student, subjects, subject_value, message):
    response = upload_note(client, "Bad subject", subject_value)
    assert response.status_code == 422
    assert message in text_of(response)
    with app.app_context():
        assert Note.query.count() == 0


def test_13_form_values_preserved_after_errors(client, student, subjects):
    response = upload_note(client, "   Kept   title  ", subjects["CS502"], filename="x.exe",
                           description="Line one\nLine two")
    body = response.get_data(as_text=True)
    assert 'value="Kept title"' in body
    assert ">Line one\nLine two</textarea>" in body
    assert f'<option value="{subjects["CS502"]}" selected>' in body


@pytest.mark.parametrize("field, value, message", [
    ("title", "   ", "Please enter a title."),
    ("title", "x" * 201, "Title must be 200 characters or fewer."),
    ("description", "x" * 5001, "Description must be 5,000 characters or fewer."),
])
def test_title_and_description_validation(app, client, student, subjects, field, value, message):
    kwargs = {"title": "Valid title", "description": ""}
    kwargs[field] = value
    response = upload_note(client, kwargs["title"], subjects["CS501"], description=kwargs["description"])
    assert response.status_code == 422
    assert message in text_of(response)


def test_path_traversal_filename_is_not_used(app, client, student, subjects):
    upload_ok(client, "Traversal", subjects["CS501"], filename="../../../evil.pdf")
    note = note_by_title(app, "Traversal")
    assert UUID_NAME.match(note.file_path)
    assert stored_files(app) == [note.file_path]


def test_database_failure_removes_saved_file(app, client, student, subjects, monkeypatch):
    def failing_commit():
        raise SQLAlchemyError("simulated failure")

    monkeypatch.setattr(db.session, "commit", failing_commit)
    response = upload_note(client, "Will fail", subjects["CS501"], description="Keep me")
    monkeypatch.undo()
    body = text_of(response)
    assert response.status_code == 500
    assert "Your note could not be saved. Please try again." in body
    assert 'value="Will fail"' in body and "Keep me" in body
    assert stored_files(app) == []
    with app.app_context():
        assert Note.query.count() == 0


def test_upload_page_lists_database_subjects(client, student, subjects):
    body = text_of(client.get("/upload"))
    assert "CS501 — Design and Analysis of Algorithms (Semester 5)" in body
    assert "CS603 — Cyber Security (Semester 6)" in body


def test_upload_page_without_subjects_explains_why(client, student):
    body = text_of(client.get("/upload"))
    assert "No subjects are available yet." in body
    assert 'name="file"' not in body


# ---------------------------------------------------------------------------
# Five sample uploads across semesters 5 and 6
# ---------------------------------------------------------------------------

SAMPLE_UPLOADS = [
    ("CS501", "Graph Algorithms Notes", "graph-notes.pdf", make_pdf),
    ("CS502", "TCP and UDP Revision Notes", "tcp-udp.docx", make_docx),
    ("CS503", "SQL and Normalization", "normalization.pptx", make_pptx),
    ("CS601", "Regression and Classification", "ml-diagram.png", make_png),
    ("CS602", "Virtualization and Service Models", "cloud.pdf", make_pdf),
]


def test_five_sample_uploads(app, client, make_user, subjects):
    user_id = sign_in(client, make_user)
    contents = {}
    for code, title, filename, maker in SAMPLE_UPLOADS:
        data = maker() if maker is not make_pdf else make_pdf(title)
        contents[title] = data
        upload_ok(client, title, subjects[code], filename=filename, data=data)

    with app.app_context():
        notes = Note.query.all()
        assert len(notes) == 5
        by_title = {n.title: n for n in notes}
        for code, title, filename, _ in SAMPLE_UPLOADS:
            note = by_title[title]
            assert note.subject.code == code
            assert note.uploader_id == user_id
            assert UUID_NAME.match(note.file_path)
            assert note.file_path.rsplit(".", 1)[1] == filename.rsplit(".", 1)[1]
        assert {n.subject.semester for n in notes} == {5, 6}
        ids = {n.title: n.id for n in notes}

    assert len(stored_files(app)) == 5
    assert sorted(card_titles(client.get("/"))) == sorted(t for _, t, _, _ in SAMPLE_UPLOADS)

    for title, note_id in ids.items():
        response = client.get(f"/note/{note_id}/download", buffered=True)
        assert response.status_code == 200
        assert response.data == contents[title]


# ---------------------------------------------------------------------------
# Homepage: visibility, search, filters, sorting, pagination (tests 14-30)
# ---------------------------------------------------------------------------

CATALOG = [
    # (title, subject code, description, status)
    ("Graph Algorithms Notes", "CS501", "BFS, DFS and shortest paths.", "active"),
    ("Sorting Algorithms Cheat Sheet", "CS501", "Merge sort and quicksort.", "active"),
    ("Routing Algorithms in Networks", "CS502", "Distance vector and link state.", "active"),
    ("TCP and UDP Revision", "CS502", "Transport layer summary.", "active"),
    ("SQL and Normalization", "CS503", "Join algorithms and normal forms.", "active"),
    ("ML Algorithms Overview", "CS601", "Regression and trees.", "active"),
    ("Virtualization Basics", "CS602", "Covers scheduling ALGORITHMS for VMs.", "active"),
    ("Cryptography Basics", "CS603", "Symmetric and public-key ciphers.", "active"),
    ("Flagged Algorithms Note", "CS501", "Hidden while under review.", "flagged"),
    ("Removed Algorithms Note", "CS501", "Removed by a moderator.", "removed"),
]


@pytest.fixture
def catalog(app, client, make_user, subjects):
    sign_in(client, make_user, email="uploader@college.example", name="Priya Uploader")
    for title, code, description, _ in CATALOG:
        upload_ok(client, title, subjects[code], description=description)
    for title, _, _, status in CATALOG:
        if status != "active":
            set_note(app, title, status=status)
    client.post("/logout", data={"csrf_token": get_csrf_token(client, "/")})
    return subjects


def browse(client, **params):
    response = client.get("/", query_string=params)
    assert response.status_code == 200
    return response


def test_14_to_16_only_active_notes_are_listed(client, catalog):
    titles = card_titles(browse(client))
    assert len(titles) == 8
    assert "Flagged Algorithms Note" not in titles
    assert "Removed Algorithms Note" not in titles
    for q in ("Flagged", "Removed"):
        assert card_titles(browse(client, q=q)) == []


def test_17_search_matches_titles(client, catalog):
    assert card_titles(browse(client, q="cheat sheet")) == ["Sorting Algorithms Cheat Sheet"]


def test_18_search_matches_descriptions(client, catalog):
    assert card_titles(browse(client, q="transport layer")) == ["TCP and UDP Revision"]


def test_case_a_search_only_is_case_insensitive(client, catalog):
    assert set(card_titles(browse(client, q="  ALGORITHMS "))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet", "Routing Algorithms in Networks",
        "SQL and Normalization", "ML Algorithms Overview", "Virtualization Basics"}


def test_19_case_b_semester_only(client, catalog):
    assert set(card_titles(browse(client, semester=5))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet", "Routing Algorithms in Networks",
        "TCP and UDP Revision", "SQL and Normalization"}
    assert set(card_titles(browse(client, semester=6))) == {
        "ML Algorithms Overview", "Virtualization Basics", "Cryptography Basics"}


def test_20_case_c_subject_only(client, catalog):
    assert set(card_titles(browse(client, subject=catalog["CS501"]))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet"}


def test_21_case_d_search_and_semester(client, catalog):
    assert set(card_titles(browse(client, q="algorithms", semester=5))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet",
        "Routing Algorithms in Networks", "SQL and Normalization"}
    assert set(card_titles(browse(client, q="algorithms", semester=6))) == {
        "ML Algorithms Overview", "Virtualization Basics"}


def test_22_case_e_search_and_subject(client, catalog):
    assert card_titles(browse(client, q="algorithms", subject=catalog["CS502"])) == [
        "Routing Algorithms in Networks"]


def test_case_f_semester_and_subject(client, catalog):
    assert set(card_titles(browse(client, semester=5, subject=catalog["CS501"]))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet"}
    # CS501 is a semester-5 subject, so asking for semester 6 + CS501 matches nothing.
    response = browse(client, semester=6, subject=catalog["CS501"])
    assert card_titles(response) == []
    assert "No notes match the selected filters." in text_of(response)


def test_23_case_g_search_semester_and_subject(client, catalog):
    assert set(card_titles(browse(client, q="algorithms", semester=5, subject=catalog["CS501"]))) == {
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet"}
    assert card_titles(browse(client, q="shortest", semester=5, subject=catalog["CS501"])) == [
        "Graph Algorithms Notes"]
    assert card_titles(browse(client, q="cheat", semester=5, subject=catalog["CS502"])) == []


def test_case_h_all_filters_with_each_sort(app, client, catalog):
    set_note(app, "Graph Algorithms Notes", avg_rating=4.8, download_count=2)
    set_note(app, "Sorting Algorithms Cheat Sheet", avg_rating=3.5, download_count=9)
    params = dict(q="algorithms", semester=5, subject=catalog["CS501"])
    # Sorting was uploaded after Graph, so it is newer.
    assert card_titles(browse(client, sort="newest", **params)) == [
        "Sorting Algorithms Cheat Sheet", "Graph Algorithms Notes"]
    assert card_titles(browse(client, sort="highest_rated", **params)) == [
        "Graph Algorithms Notes", "Sorting Algorithms Cheat Sheet"]
    assert card_titles(browse(client, sort="most_downloaded", **params)) == [
        "Sorting Algorithms Cheat Sheet", "Graph Algorithms Notes"]


def test_case_j_no_matching_results(client, catalog):
    response = browse(client, q="quantum chromodynamics")
    assert card_titles(response) == []
    body = text_of(response)
    assert "No notes match your search." in body
    assert 'href="/">Clear search</a>' in response.get_data(as_text=True)


def test_30_empty_states(client, subjects):
    assert "No notes have been uploaded yet." in text_of(browse(client))
    assert "No notes match your search." in text_of(browse(client, q="anything"))
    assert "No notes match the selected filters." in text_of(browse(client, semester=5))


def test_selected_filters_are_kept_in_the_form(client, catalog):
    body = browse(client, q="graph", semester=5, subject=catalog["CS501"],
                  sort="most_downloaded").get_data(as_text=True)
    assert 'name="q" value="graph"' in body
    assert '<option value="5" selected>' in body
    assert f'<option value="{catalog["CS501"]}" selected>' in body
    assert '<option value="most_downloaded" selected>' in body


@pytest.mark.parametrize("params", [
    {"semester": "abc"}, {"semester": "99"}, {"subject": "xyz"}, {"subject": "999999"},
    {"page": "abc"}, {"page": "-3"}, {"page": "0"}, {"sort": "drop table notes"},
    {"q": "' OR 1=1 --"}, {"q": "x" * 5000}, {"page": "99999999999999999999"},
])
def test_malformed_parameters_never_crash(client, catalog, params):
    response = client.get("/", query_string=params)
    assert response.status_code in (200, 302)


def test_27_invalid_sort_falls_back_to_newest(client, catalog):
    assert card_titles(browse(client, sort="bogus")) == card_titles(browse(client, sort="newest"))


def test_like_wildcards_in_search_are_literal(client, catalog):
    assert card_titles(browse(client, q="%")) == []
    assert card_titles(browse(client, q="_")) == []


def test_24_to_26_sorting(app, client, make_user, subjects):
    sign_in(client, make_user)
    for title in ("Note A", "Note B", "Note C"):
        upload_ok(client, title, subjects["CS501"])
    set_note(app, "Note A", avg_rating=3.0, download_count=10)
    set_note(app, "Note B", avg_rating=4.5, download_count=2)
    set_note(app, "Note C", avg_rating=4.5, download_count=10)
    assert card_titles(browse(client, sort="newest")) == ["Note C", "Note B", "Note A"]
    # Ties are broken by newest first, so the order is always the same.
    assert card_titles(browse(client, sort="highest_rated")) == ["Note C", "Note B", "Note A"]
    assert card_titles(browse(client, sort="most_downloaded")) == ["Note C", "Note A", "Note B"]


@pytest.fixture
def big_catalog(app, client, make_user, subjects):
    """15 matching notes plus non-matching noise, for pagination tests."""
    sign_in(client, make_user)
    for i in range(1, 16):
        upload_ok(client, f"Algorithms Practice Set {i:02d}", subjects["CS501"])
    upload_ok(client, "Algorithms in Machine Learning", subjects["CS601"])  # other semester
    upload_ok(client, "Practice Set for Networks", subjects["CS502"])       # other subject
    upload_ok(client, "Hidden Algorithms Practice", subjects["CS501"])
    set_note(app, "Hidden Algorithms Practice", status="flagged")
    return subjects


def test_28_case_i_pagination_after_combined_filters(client, big_catalog):
    params = dict(q="algorithms", semester=5, subject=big_catalog["CS501"], sort="newest")
    page1 = browse(client, **params)
    titles1 = card_titles(page1)
    assert len(titles1) == 12
    assert titles1[0] == "Algorithms Practice Set 15"
    assert "Showing 1–12 of 15 notes" in text_of(page1)

    # 29: the Next link keeps every filter and the sort order.
    path, query = link_query(page1, "next")
    assert path == "/"
    assert query == {"q": "algorithms", "semester": "5", "subject": str(big_catalog["CS501"]),
                     "sort": "newest", "page": "2"}

    page2 = browse(client, **query)
    titles2 = card_titles(page2)
    assert titles2 == ["Algorithms Practice Set 03", "Algorithms Practice Set 02",
                       "Algorithms Practice Set 01"]
    assert set(titles1).isdisjoint(titles2)
    _, prev_query = link_query(page2, "prev")
    assert prev_query == {**query, "page": "1"}
    assert 'aria-disabled="true">Next</span>' in page2.get_data(as_text=True)


def test_pagination_without_filters_and_beyond_last_page(client, big_catalog):
    page1 = browse(client)
    assert len(card_titles(page1)) == 12  # 17 active notes; the flagged one is hidden
    assert len(card_titles(browse(client, page=2))) == 5

    response = client.get("/", query_string={"q": "algorithms", "page": 99})
    assert response.status_code == 302
    path, query = urlsplit(response.headers["Location"]).path, parse_qs(urlsplit(response.headers["Location"]).query)
    assert path == "/" and query == {"q": ["algorithms"], "page": ["2"]}


# ---------------------------------------------------------------------------
# Note details (tests 31-36)
# ---------------------------------------------------------------------------

def add_rating(app, note_id, student_id, stars, comment=None):
    with app.app_context():
        db.session.add(Rating(note_id=note_id, student_id=student_id, stars=stars, comment=comment))
        db.session.flush()
        db.session.get(Note, note_id).update_avg_rating()
        db.session.commit()


def test_31_active_note_details(app, client, make_user, subjects):
    sign_in(client, make_user, name="Asha Kulkarni")
    upload_ok(client, "Graph Algorithms Notes", subjects["CS501"],
              description="Unit 3.\nBFS and DFS.")
    note = note_by_title(app, "Graph Algorithms Notes")
    client.post("/logout", data={"csrf_token": get_csrf_token(client, "/")})

    response = client.get(f"/note/{note.id}")  # anonymous visitors may view active notes
    body = text_of(response)
    assert response.status_code == 200
    for expected in ("Graph Algorithms Notes", "Unit 3.\nBFS and DFS.", "CS501",
                     "Design and Analysis of Algorithms", "Semester 5", "Asha Kulkarni",
                     note.upload_date.strftime("%d %b %Y"), "No ratings yet.", "Log in to download"):
        assert expected in body
    assert note.file_path not in body  # the storage name is never shown


def test_32_33_rating_summary_and_reviews(app, client, make_user, subjects):
    owner = sign_in(client, make_user)
    upload_ok(client, "Rated note", subjects["CS501"])
    note = note_by_title(app, "Rated note")
    reviewers = [make_user(email=f"r{i}@college.example", name=f"Reviewer {i}") for i in range(3)]
    add_rating(app, note.id, reviewers[0], 5, "Clear and complete.")
    add_rating(app, note.id, reviewers[1], 4, "<b>Bold</b> claim")
    add_rating(app, note.id, reviewers[2], 4)

    response = client.get(f"/note/{note.id}")
    raw = response.get_data(as_text=True)
    body = text_of(response)
    assert "4.3" in body and "from 3 ratings" in body
    assert "Reviewer 0" in body and "Reviewer 1" in body and "Reviewer 2" in body
    assert "Clear and complete." in body
    assert 'aria-label="4 out of 5 stars"' in raw and 'aria-label="5 out of 5 stars"' in raw
    assert "<b>Bold</b>" not in raw and "&lt;b&gt;Bold&lt;/b&gt;" in raw
    # Newest first.
    assert raw.index("Reviewer 2") < raw.index("Reviewer 1") < raw.index("Reviewer 0")
    # The listing uses the maintained avg_rating.
    assert note_by_title(app, "Rated note").avg_rating == 4.33


def test_34_missing_note_returns_404(client):
    assert client.get("/note/999999").status_code == 404


@pytest.mark.parametrize("status, label", [("flagged", "Flagged / Under Review"), ("removed", "Removed")])
def test_35_36_non_active_note_visibility(app, client, make_user, subjects, status, label):
    sign_in(client, make_user, email="owner@college.example")
    upload_ok(client, "Hidden note", subjects["CS501"])
    note = note_by_title(app, "Hidden note")
    set_note(app, "Hidden note", status=status)

    owner_view = client.get(f"/note/{note.id}")                         # 36
    assert owner_view.status_code == 200
    assert f"Status: {label}." in text_of(owner_view)

    other = client.application.test_client()
    assert other.get(f"/note/{note.id}").status_code == 404           # anonymous
    sign_in(other, make_user, email="other@college.example")
    assert other.get(f"/note/{note.id}").status_code == 404           # 35

    moderator = client.application.test_client()
    sign_in(moderator, make_user, email="mod@college.example", role="moderator")
    assert moderator.get(f"/note/{note.id}").status_code == 200


def test_back_to_results_link_is_kept_only_when_safe(app, client, student, subjects):
    upload_ok(client, "Back link", subjects["CS501"])
    note = note_by_title(app, "Back link")
    raw = client.get(f"/note/{note.id}", query_string={"back": "/?q=back&page=1"}).get_data(as_text=True)
    assert 'href="/?q=back&amp;page=1">Back to results' in raw
    for bad in ("https://evil.example/", "//evil.example", "/login"):
        raw = client.get(f"/note/{note.id}", query_string={"back": bad}).get_data(as_text=True)
        assert "Back to results" not in raw


# ---------------------------------------------------------------------------
# Downloads (tests 37-42)
# ---------------------------------------------------------------------------

def download_count(app, note_id):
    with app.app_context():
        return db.session.get(Note, note_id).download_count


@pytest.fixture
def uploaded(app, client, make_user, subjects):
    """One active PDF note uploaded by the signed-in owner; returns (note, bytes)."""
    sign_in(client, make_user, email="owner@college.example")
    data = make_pdf("Download me")
    upload_ok(client, "Download me", subjects["CS501"], filename="original name.pdf", data=data)
    return note_by_title(app, "Download me"), data


def test_37_download_requires_login(app, uploaded):
    note, _ = uploaded
    anonymous = app.test_client()
    response = anonymous.get(f"/note/{note.id}/download", buffered=True)
    assert response.status_code == 302
    assert response.headers["Location"] == f"/login?next=/note/{note.id}/download"
    assert download_count(app, note.id) == 0


def test_38_39_download_returns_file_and_counts(app, client, make_user, uploaded):
    note, data = uploaded
    reader = app.test_client()
    sign_in(reader, make_user, email="reader@college.example")

    response = reader.get(f"/note/{note.id}/download", buffered=True)
    assert response.status_code == 200
    assert response.data == data
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "Download_me.pdf" in response.headers["Content-Disposition"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.mimetype == "application/pdf"
    assert download_count(app, note.id) == 1

    reader.get(f"/note/{note.id}/download", buffered=True)
    assert download_count(app, note.id) == 2


def test_40_missing_file_is_handled(app, client, uploaded, caplog):
    note, _ = uploaded
    os.remove(os.path.join(app.config["UPLOAD_FOLDER"], note.file_path))
    response = client.get(f"/note/{note.id}/download", buffered=True)
    body = text_of(response)
    assert response.status_code == 404
    assert "The file for this note is unavailable right now." in body
    assert app.config["UPLOAD_FOLDER"] not in body and note.file_path not in body
    assert download_count(app, note.id) == 0
    assert any("missing" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("status", ["flagged", "removed"])
def test_41_non_active_downloads(app, client, make_user, uploaded, status):
    note, data = uploaded
    set_note(app, "Download me", status=status)

    other = app.test_client()
    sign_in(other, make_user, email="other@college.example")
    assert other.get(f"/note/{note.id}/download", buffered=True).status_code == 404
    assert download_count(app, note.id) == 0

    own = client.get(f"/note/{note.id}/download", buffered=True)       # the uploader still can
    assert own.status_code == 200 and own.data == data

    moderator = app.test_client()
    sign_in(moderator, make_user, email="mod@college.example", role="moderator")
    assert moderator.get(f"/note/{note.id}/download", buffered=True).status_code == 200


@pytest.mark.parametrize("bad_path", ["../conftest.py", "..\\..\\config.py", "/etc/passwd",
                                      "C:\\Windows\\win.ini", "../" + "a" * 32 + ".pdf",
                                      "not-a-uuid.pdf", ""])
def test_42_unsafe_stored_paths_are_rejected(app, client, uploaded, bad_path):
    note, _ = uploaded
    set_note(app, "Download me", file_path=bad_path or "x")
    response = client.get(f"/note/{note.id}/download", buffered=True)
    assert response.status_code == 404
    assert b"import" not in response.data and b"root:" not in response.data
    assert download_count(app, note.id) == 0


def test_only_app_generated_file_names_are_served(app, client, uploaded):
    """Even a real file inside the upload folder is refused unless its name is
    one this app generated (32 hex characters + an allowed extension)."""
    note, data = uploaded
    with open(os.path.join(app.config["UPLOAD_FOLDER"], "handmade.pdf"), "wb") as fh:
        fh.write(data)
    set_note(app, "Download me", file_path="handmade.pdf")
    assert client.get(f"/note/{note.id}/download", buffered=True).status_code == 404
    assert download_count(app, note.id) == 0


def test_upload_folder_is_not_publicly_served(app, client, uploaded):
    note, _ = uploaded
    for path in (f"/uploads/{note.file_path}", f"/static/../uploads/{note.file_path}",
                 f"/static/{note.file_path}"):
        assert client.get(path).status_code == 404


# ---------------------------------------------------------------------------
# My Notes and delete (tests 43-50)
# ---------------------------------------------------------------------------

def test_43_44_my_notes_shows_only_own_notes_with_status(app, client, make_user, subjects):
    other = app.test_client()
    sign_in(other, make_user, email="other@college.example")
    upload_ok(other, "Someone else's note", subjects["CS501"])

    sign_in(client, make_user)
    for title in ("My active note", "My flagged note", "My removed note"):
        upload_ok(client, title, subjects["CS502"])
    set_note(app, "My flagged note", status="flagged")
    set_note(app, "My removed note", status="removed")

    body = text_of(client.get("/my-notes"))
    assert "My active note" in body and "My flagged note" in body and "My removed note" in body
    assert "Someone else's note" not in body
    assert "Flagged / Under Review" in body
    assert ">Removed<" in body and ">Active<" in body
    assert "3 notes" in body


def test_my_notes_empty_state_and_login(app, client, student):
    assert "You haven't uploaded any notes yet." in text_of(client.get("/my-notes"))
    assert app.test_client().get("/my-notes").status_code == 302


def delete_note(client, note_id, token_page="/my-notes"):
    return client.post(f"/note/{note_id}/delete", data={"csrf_token": get_csrf_token(client, token_page)})


def test_45_48_49_delete_own_note_with_related_records(app, client, make_user, subjects):
    owner_id = sign_in(client, make_user)
    upload_ok(client, "Delete me", subjects["CS501"])
    upload_ok(client, "Keep me", subjects["CS501"])
    doomed, kept = note_by_title(app, "Delete me"), note_by_title(app, "Keep me")
    rater = make_user(email="rater@college.example")
    add_rating(app, doomed.id, rater, 5, "On the deleted note")
    add_rating(app, kept.id, rater, 4, "On the kept note")
    with app.app_context():
        db.session.add_all([Report(note_id=doomed.id, reporter_id=rater, reason="test"),
                            Report(note_id=kept.id, reporter_id=rater, reason="test")])
        db.session.commit()

    response = delete_note(client, doomed.id)
    assert response.status_code == 302
    assert response.headers["Location"] == "/my-notes"
    assert "“Delete me” has been deleted." in text_of(client.get("/my-notes"))

    with app.app_context():
        assert db.session.get(Note, doomed.id) is None
        assert Rating.query.filter_by(note_id=doomed.id).count() == 0
        assert Report.query.filter_by(note_id=doomed.id).count() == 0
        assert db.session.get(Note, kept.id) is not None                     # 49
        assert Rating.query.filter_by(note_id=kept.id).count() == 1
        assert Report.query.filter_by(note_id=kept.id).count() == 1
        assert db.session.get(User, owner_id) is not None
    assert stored_files(app) == [kept.file_path]


def test_46_cannot_delete_another_students_note(app, client, make_user, subjects):
    owner = app.test_client()
    sign_in(owner, make_user, email="owner@college.example")
    upload_ok(owner, "Not yours", subjects["CS501"])
    note = note_by_title(app, "Not yours")

    sign_in(client, make_user, email="attacker@college.example")
    response = delete_note(client, note.id, token_page="/")
    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(Note, note.id) is not None
    assert stored_files(app) == [note.file_path]

    # A moderator can view other students' notes but still cannot delete them here.
    moderator = app.test_client()
    sign_in(moderator, make_user, email="mod@college.example", role="moderator")
    assert delete_note(moderator, note.id, token_page="/").status_code == 403


def test_47_get_cannot_delete(app, client, student, subjects):
    upload_ok(client, "Still here", subjects["CS501"])
    note = note_by_title(app, "Still here")
    assert client.get(f"/note/{note.id}/delete").status_code == 405
    assert client.post(f"/note/{note.id}/delete").status_code == 400   # no CSRF token
    with app.app_context():
        assert db.session.get(Note, note.id) is not None


def test_50_deleting_missing_note_returns_404(client, student):
    assert delete_note(client, 999999).status_code == 404


def test_owner_cannot_delete_note_under_review(app, client, student, subjects):
    """Phase 4: a flagged note (and its reports) is kept until a moderator decides."""
    upload_ok(client, "Flagged own", subjects["CS501"])
    note = note_by_title(app, "Flagged own")
    set_note(app, "Flagged own", status="flagged")
    response = delete_note(client, note.id)
    assert response.status_code == 302 and response.headers["Location"] == "/my-notes"
    assert "can't be deleted until the review is finished" in text_of(client.get("/my-notes"))
    with app.app_context():
        assert db.session.get(Note, note.id) is not None
    assert stored_files(app) == [note.file_path]

    set_note(app, "Flagged own", status="removed")   # removed notes can still be deleted
    assert delete_note(client, note.id).status_code == 302
    with app.app_context():
        assert db.session.get(Note, note.id) is None


# ---------------------------------------------------------------------------
# Banned users and navigation
# ---------------------------------------------------------------------------

def test_banned_user_cannot_upload_download_or_delete(app, client, make_user, subjects):
    user_id = sign_in(client, make_user)
    upload_ok(client, "Before ban", subjects["CS501"])
    note = note_by_title(app, "Before ban")
    token = get_csrf_token(client, "/my-notes")
    with app.app_context():
        db.session.get(User, user_id).is_banned = True
        db.session.commit()

    # The first request after the ban is refused and clears the session.
    response = client.post(f"/note/{note.id}/delete", data={"csrf_token": token})
    assert response.status_code == 302 and response.headers["Location"] == "/login"
    # Later requests have no session at all, so they are sent to log in.
    assert client.get(f"/note/{note.id}/download", buffered=True).headers["Location"].startswith("/login")
    with app.app_context():
        assert db.session.get(Note, note.id) is not None
        assert db.session.get(Note, note.id).download_count == 0
    assert client.get("/upload").headers["Location"].startswith("/login")
    response = client.post("/upload", data={"csrf_token": token, "title": "After ban",
                                            "subject_id": subjects["CS501"],
                                            "file": (io.BytesIO(make_pdf()), "x.pdf")},
                           content_type="multipart/form-data")
    assert response.status_code in (302, 400)  # no session (and so no valid CSRF token)
    with app.app_context():
        assert Note.query.count() == 1


def test_navigation_links_now_work(client, student):
    raw = client.get("/my-notes").get_data(as_text=True)
    assert 'href="/">Browse</a>' in raw
    assert 'href="/upload">Upload</a>' in raw
    assert 'href="/my-notes" aria-current="page">My Notes</a>' in raw
