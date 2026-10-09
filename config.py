"""
Application configuration for NoteShare.

All secrets and environment-specific values come from environment variables,
which are loaded from the project's `.env` file (see `.env.example`).

Importing this module never opens a database connection. Call
`Config.validate()` (done automatically by `app.create_app()`) to check that
the required settings are present before the application starts.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# Absolute path of the project directory (the folder containing this file).
# Every relative path below is resolved against it, so behaviour does not
# depend on the terminal's current working directory.
BASE_DIR = Path(__file__).resolve().parent

# Load variables from <project>/.env. Variables that are already set in the
# real environment take precedence over values in the file.
load_dotenv(BASE_DIR / ".env")

# Values copied verbatim from .env.example. If they are still present, the
# developer has not finished configuring the application.
_PLACEHOLDER_SECRET_KEY = "replace-with-a-long-random-secret"
_PLACEHOLDER_DB_PASSWORD = "CHANGE_ME"
_MIN_SECRET_KEY_LENGTH = 32


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _resolve_path(value: str) -> str:
    """Return an absolute path; relative paths are anchored at BASE_DIR."""
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


class Config:
    # --- Security -----------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

    # Session cookie: not readable from JavaScript, and not sent on cross-site
    # POSTs. SESSION_COOKIE_SECURE must be true behind HTTPS in production; it
    # stays false by default because browsers drop Secure cookies on plain
    # http://127.0.0.1, which would break local logins.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)

    # CSRF (Flask-WTF). Tokens are bound to the session and stay valid for as
    # long as it does, so a form left open for a while still submits.
    WTF_CSRF_TIME_LIMIT = None

    # Public address of the site, e.g. https://noteshare.example.edu. Used for
    # canonical links, the sitemap, robots.txt and social-share tags. When it
    # is empty (local development) the address of the current request is
    # used instead. Set it in production so those URLs cannot be influenced
    # by the request's Host header.
    SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")

    # --- Database (Flask-SQLAlchemy reads SQLALCHEMY_DATABASE_URI) ----------
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "").strip()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Test pooled connections before use; MySQL drops idle connections
        # after `wait_timeout`, which otherwise causes "server has gone away".
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # --- File uploads (used from a later phase onwards) ---------------------
    UPLOAD_FOLDER = _resolve_path(os.environ.get("UPLOAD_FOLDER", "uploads").strip() or "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # exactly 10 MiB
    ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "jpg", "png"})

    @classmethod
    def validate(cls) -> None:
        """Raise ConfigError describing every problem with the configuration.

        Error messages never include the database password or secret key.
        """
        problems = []

        if not cls.SQLALCHEMY_DATABASE_URI:
            problems.append(
                "DATABASE_URL is not set. Add a line like\n"
                "    DATABASE_URL=mysql+pymysql://noteshare_user:<password>@localhost:3306/noteshare\n"
                "  to your .env file."
            )
        else:
            try:
                url = make_url(cls.SQLALCHEMY_DATABASE_URI)
            except ArgumentError:
                problems.append(
                    "DATABASE_URL is not a valid database URL. Expected the form\n"
                    "    mysql+pymysql://<user>:<password>@<host>:<port>/<database>"
                )
            else:
                # NoteShare deliberately supports MySQL only; refuse anything
                # else rather than silently writing to an unintended database.
                if url.drivername != "mysql+pymysql":
                    problems.append(
                        f"DATABASE_URL uses the '{url.drivername}' driver. NoteShare requires "
                        "MySQL through PyMySQL, so the URL must start with 'mysql+pymysql://'."
                    )
                if not url.database:
                    problems.append("DATABASE_URL does not name a database (e.g. '.../noteshare').")
                if url.password == _PLACEHOLDER_DB_PASSWORD:
                    problems.append(
                        "DATABASE_URL still contains the placeholder password 'CHANGE_ME' "
                        "from .env.example. Replace it with the real MySQL password."
                    )

        if not cls.SECRET_KEY:
            problems.append(
                "SECRET_KEY is not set. Generate one with\n"
                '    python -c "import secrets; print(secrets.token_hex(32))"\n'
                "  and add SECRET_KEY=<value> to your .env file."
            )
        elif cls.SECRET_KEY == _PLACEHOLDER_SECRET_KEY:
            problems.append(
                "SECRET_KEY still has the placeholder value from .env.example. Generate a real one with\n"
                '    python -c "import secrets; print(secrets.token_hex(32))"'
            )
        elif len(cls.SECRET_KEY) < _MIN_SECRET_KEY_LENGTH:
            problems.append(
                f"SECRET_KEY is too short ({len(cls.SECRET_KEY)} characters). "
                f"Use at least {_MIN_SECRET_KEY_LENGTH} random characters."
            )

        if cls.SITE_URL:
            parts = urlsplit(cls.SITE_URL)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
                problems.append(
                    "SITE_URL must be just the site's address, like https://noteshare.example.edu "
                    "(no path or query string). Leave it empty for local development."
                )

        if problems:
            details = "\n".join(f"- {p}" for p in problems)
            raise ConfigError(
                f"NoteShare is not configured correctly ({BASE_DIR / '.env'}):\n{details}"
            )
