"""
Shared pytest fixtures for NoteShare.

Tests run against a separate MySQL database named by TEST_DATABASE_URL (in
.env), never against DATABASE_URL. Every row in that database is deleted
before and after each test, so the guard below refuses to run unless the
database name ends in "_test" and differs from the development database.

CSRF protection stays ON in tests, so forms are submitted with real tokens.
"""

import os
import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

import config  # loads .env
from app import create_app
from auth import login_required, role_required
from models import User, db

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
def app():
    _check_test_database()
    app = create_app(TestConfig)
    _register_test_routes(app)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(app):
    with app.app_context():
        _delete_all_rows()
    yield
    with app.app_context():
        db.session.rollback()
        _delete_all_rows()


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
