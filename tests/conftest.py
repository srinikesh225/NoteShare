"""
Shared pytest fixtures for NoteShare.

Tests run against a separate MySQL database named by TEST_DATABASE_URL (in
.env), never against DATABASE_URL. Every row in that database is deleted
before and after each test, so the guard below refuses to run unless the
database name ends in "_test" and differs from the development database.

CSRF protection stays ON in tests, so forms are submitted with real tokens.
"""

import io
import os
import re
import struct
import zipfile
import zlib

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

import config  # loads .env
from app import create_app
from auth import login_required, role_required
from migrate import apply_migrations
from models import Subject, User, db
from seed import SEED_SUBJECTS

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
TABLES_CHILD_FIRST = ("reports", "ratings", "notes", "users", "subjects")
CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _check_test_database():
    if not TEST_DATABASE_URL:
        pytest.exit("TEST_DATABASE_URL is not set in .env. See README, 'Running the tests'.",
                    returncode=2)
    test_url = make_url(TEST_DATABASE_URL)
    if test_url.drivername != "mysql+pymysql":
        pytest.exit("TEST_DATABASE_URL must be a mysql+pymysql:// URL.", returncode=2)
    if not (test_url.database or "").endswith("_test"):
        pytest.exit("Refusing to run: the TEST_DATABASE_URL database name must end in '_test'.",
                    returncode=2)
    if config.Config.SQLALCHEMY_DATABASE_URI:
        dev_url = make_url(config.Config.SQLALCHEMY_DATABASE_URI)
        if (dev_url.host, dev_url.port, dev_url.database) == (test_url.host, test_url.port, test_url.database):
            pytest.exit("Refusing to run: TEST_DATABASE_URL points at the development database.",
                        returncode=2)


class TestConfig(config.Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL


def _register_test_routes(app):
    """Routes that exist only in the test app, to exercise the decorators."""
    app.add_url_rule("/_test/student", "test_student",
                     login_required(lambda: "student area"))
    app.add_url_rule("/_test/moderator", "test_moderator",
                     role_required("moderator")(lambda: "moderator area"))
    app.add_url_rule("/_test/admin", "test_admin",
                     role_required("admin")(lambda: "admin area"))


def _delete_all_rows():
    for table in TABLES_CHILD_FIRST:
        db.session.execute(text(f"DELETE FROM {table}"))
    db.session.commit()


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    _check_test_database()
    app = create_app(TestConfig)
    # Uploaded test files go to a temporary folder, never the real uploads/.
    app.config["UPLOAD_FOLDER"] = str(tmp_path_factory.mktemp("uploads"))
    _register_test_routes(app)
    with app.app_context():
        db.create_all()
        apply_migrations(db.engine)
    yield app
    with app.app_context():
        db.engine.dispose()


def _empty_upload_folder(app):
    folder = app.config["UPLOAD_FOLDER"]
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))


@pytest.fixture(autouse=True)
def clean_database(app):
    with app.app_context():
        _delete_all_rows()
    _empty_upload_folder(app)
    yield
    with app.app_context():
        db.session.rollback()
        _delete_all_rows()
    _empty_upload_folder(app)


@pytest.fixture
def subjects(app):
    """Insert the six subjects from seed.py; return {code: id}."""
    with app.app_context():
        rows = [Subject(**spec) for spec in SEED_SUBJECTS]
        db.session.add_all(rows)
        db.session.commit()
        return {s.code: s.id for s in rows}


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    """Create a user directly in the test database and return its id."""

    def _make(email="asha@college.example", password="correct-password", role="student",
              is_banned=False, name="Asha Kulkarni"):
        with app.app_context():
            user = User(name=name, email=email, password_hash=generate_password_hash(password),
                        role=role, branch="Computer Science and Engineering", year=3,
                        is_banned=is_banned)
            db.session.add(user)
            db.session.commit()
            return user.id

    return _make


def get_csrf_token(client, path):
    response = client.get(path)
    match = CSRF_PATTERN.search(response.get_data(as_text=True))
    assert match, f"no CSRF token found on {path}"
    return match.group(1)


def log_in(client, email, password, next_url=None):
    data = {"csrf_token": get_csrf_token(client, "/login"), "email": email, "password": password}
    if next_url is not None:
        data["next"] = next_url
    return client.post("/login", data=data)


# ---------------------------------------------------------------------------
# Small but genuinely valid test files
# ---------------------------------------------------------------------------

def make_pdf(text="NoteShare test file"):
    """A minimal, valid one-page PDF with a correct cross-reference table."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _make_office(main_part, content_type):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                         f'package/2006/content-types"><Override PartName="/{main_part}" '
                         f'ContentType="{content_type}"/></Types>')
        archive.writestr(main_part, '<?xml version="1.0"?><root/>')
    return buffer.getvalue()


def make_docx():
    return _make_office("word/document.xml",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")


def make_pptx():
    return _make_office("ppt/presentation.xml",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")


def make_png():
    """A valid 1x1 transparent PNG (chunks with correct CRCs)."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit RGBA
    pixels = zlib.compress(b"\x00" + b"\x00\x00\x00\x00")  # filter byte + one pixel
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels)
            + chunk(b"IEND", b""))


def upload_note(client, title, subject_id, filename="notes.pdf", data=None, description="", **extra):
    """Submit the real upload form (with CSRF token) and return the response."""
    form = {
        "csrf_token": get_csrf_token(client, "/upload"),
        "title": title,
        "description": description,
        "subject_id": str(subject_id),
        "file": (io.BytesIO(make_pdf(title) if data is None else data), filename),
        **extra,
    }
    return client.post("/upload", data=form, content_type="multipart/form-data")
