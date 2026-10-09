"""
Authentication and role-based access control for NoteShare.

Session model
-------------
The signed Flask session cookie holds only `user_id` (plus Flask-WTF's CSRF
token). Everything else — the user's name, role and ban status — is read from
MySQL on every request by get_current_user(), so changing a role or banning a
user in the database takes effect on the user's next request.

Decorators
----------
@login_required          any signed-in, non-banned user
@role_required("moderator")  moderators and admins
@role_required("admin")      admins only

role_required() includes login_required, so a route needs only one of them.
Role inheritance is defined once, in models.ROLE_LEVELS.
"""

import re
from functools import wraps
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from models import ROLE_LEVELS, User, db

bp = Blueprint("auth", __name__)

SUSPENDED_MESSAGE = "Your account has been suspended."
INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
DUPLICATE_EMAIL_MESSAGE = "An account with this email already exists."

# Where users land after logging in when no (safe) `next` URL was given.
DEFAULT_ENDPOINT = "notes.browse"

NAME_MAX_LENGTH = User.name.type.length        # 100
EMAIL_MAX_LENGTH = User.email.type.length      # 255
BRANCH_MAX_LENGTH = User.branch.type.length    # 100
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
YEAR_CHOICES = range(1, 7)  # years 1-6, matching ck_users_year_range in MySQL

# The same rule browsers use for <input type="email">, plus a required dot in
# the domain so that "name@localhost" is rejected.
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Navigation for future features: (label, endpoint, minimum role). Items whose
# endpoint does not exist yet are shown as disabled "Soon" entries; once a
# later phase registers the endpoint, the link turns on automatically.
NAV_ITEMS = [
    ("Browse", "notes.browse", "student"),
    ("Upload", "notes.upload", "student"),
    ("My Notes", "notes.mine", "student"),
    ("Reports", "moderation.reports", "moderator"),
    ("Users", "moderation.users", "moderator"),
    ("Subjects", "admin.subjects", "admin"),
]
SEARCH_ENDPOINT = "notes.browse"  # the homepage handles ?q= searches


# --------------------------------------------------------------------------
# Current user
# --------------------------------------------------------------------------

def get_current_user():
    """Return the signed-in User, or None.

    The result is cached on `g` for the rest of the request. A session whose
    user no longer exists, or is banned, is cleared; for a banned user the
    suspension message is flashed and `g.session_suspended` is set.
    """
    if "current_user" in g:
        return g.current_user

    user = None
    user_id = session.get("user_id")
    if user_id is not None:
        user = db.session.get(User, user_id) if isinstance(user_id, int) else None
        if user is None:
            session.clear()
        elif user.is_banned:
            session.clear()
            flash(SUSPENDED_MESSAGE, "error")
            g.session_suspended = True
            user = None

    g.current_user = user
    return user


def _log_in(user):
    # Start from an empty session so nothing from before login (including a
    # session ID an attacker may have planted) carries over.
    session.clear()
    session["user_id"] = user.id
    g.current_user = user


# --------------------------------------------------------------------------
# Decorators
# --------------------------------------------------------------------------

def login_required(view):
    """Allow only signed-in, non-banned users; otherwise redirect to /login."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if get_current_user() is None:
            if g.get("session_suspended"):
                return redirect(url_for("auth.login"))
            flash("Please log in to continue.", "info")
            next_url = None
            if request.method == "GET":
                next_url = request.full_path.rstrip("?")
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


def role_required(role):
    """Allow only users whose role is `role` or higher; otherwise HTTP 403.

    Includes login_required: anonymous visitors are redirected to /login.
    """
    if role not in ROLE_LEVELS:
        raise ValueError(f"Unknown role {role!r}; expected one of {sorted(ROLE_LEVELS)}")

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not g.current_user.has_role(role):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def normalize_email(value):
    return (value or "").strip().lower()


def safe_next_url(target):
    """Return `target` if it is a safe same-site path to redirect to, else None."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return None
    # Browsers treat "\" like "/", so "/\evil.example" would leave the site.
    if any(ch in target for ch in "\\\r\n\t"):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    # Never send someone back to an auth page (avoids loops).
    if parts.path in {url_for("auth.login"), url_for("auth.register"), url_for("auth.logout")}:
        return None
    return target


_dummy_hash = None


def _verify_password(user, password):
    """check_password_hash, also run for unknown emails so that the response
    time does not reveal whether an account exists."""
    global _dummy_hash
    if user is None:
        if _dummy_hash is None:
            _dummy_hash = generate_password_hash("not-a-real-password")
        check_password_hash(_dummy_hash, password)
        return False
    return check_password_hash(user.password_hash, password)


def _validate_registration(data):
    """Return (cleaned form values, field errors, password)."""
    form = {
        "name": " ".join((data.get("name") or "").split()),
        "email": normalize_email(data.get("email")),
        "branch": " ".join((data.get("branch") or "").split()),
        "year": (data.get("year") or "").strip(),
    }
    password = data.get("password") or ""
    errors = {}

    if not form["name"]:
        errors["name"] = "Please enter your name."
    elif len(form["name"]) > NAME_MAX_LENGTH:
        errors["name"] = f"Name must be {NAME_MAX_LENGTH} characters or fewer."

    if not form["email"]:
        errors["email"] = "Please enter your college email."
    elif len(form["email"]) > EMAIL_MAX_LENGTH or not EMAIL_PATTERN.match(form["email"]):
        errors["email"] = "Enter a valid email address, like name@college.edu."

    if not password:
        errors["password"] = "Please choose a password."
    elif len(password) < PASSWORD_MIN_LENGTH:
        errors["password"] = f"Password must contain at least {PASSWORD_MIN_LENGTH} characters."
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors["password"] = f"Password must be {PASSWORD_MAX_LENGTH} characters or fewer."

    if not form["branch"]:
        errors["branch"] = "Please enter your branch."
    elif len(form["branch"]) > BRANCH_MAX_LENGTH:
        errors["branch"] = f"Branch must be {BRANCH_MAX_LENGTH} characters or fewer."

    if not form["year"]:
        errors["year"] = "Please select your year."
    elif not form["year"].isdigit() or int(form["year"]) not in YEAR_CHOICES:
        errors["year"] = f"Enter a valid college year ({YEAR_CHOICES[0]}–{YEAR_CHOICES[-1]})."

    return form, errors, password


def _email_registered(email):
    return User.query.filter_by(email=email).first() is not None


def _is_duplicate_email_error(exc):
    orig = getattr(exc, "orig", None)
    return bool(orig and orig.args and orig.args[0] == 1062 and "uq_users_email" in str(orig))


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@bp.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user() is not None:
        return redirect(url_for(DEFAULT_ENDPOINT))

    form = {"name": "", "email": "", "branch": "", "year": ""}
    errors = {}

    if request.method == "POST":
        form, errors, password = _validate_registration(request.form)

        # Check for an existing account whenever the email itself is valid,
        # so the user learns about it in the same round as any other errors.
        if "email" not in errors and _email_registered(form["email"]):
            errors["email"] = DUPLICATE_EMAIL_MESSAGE

        if not errors:
            # Only these fields come from the form. The role is always set
            # here on the server; warnings and is_banned use the model
            # defaults (0 / False). Any extra submitted fields are ignored.
            user = User(
                name=form["name"],
                email=form["email"],
                password_hash=generate_password_hash(password),
                branch=form["branch"],
                year=int(form["year"]),
                role="student",
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                # Another request registered the same email between our check
                # and the insert; MySQL's unique key caught it.
                if not _is_duplicate_email_error(exc):
                    raise
                errors["email"] = DUPLICATE_EMAIL_MESSAGE
            else:
                flash("Registration successful! You can now log in.", "success")
                return redirect(url_for("auth.login"))

        flash("Please correct the highlighted fields.", "error")
        return render_template("register.html", form=form, errors=errors,
                               years=YEAR_CHOICES), 422

    return render_template("register.html", form=form, errors=errors, years=YEAR_CHOICES)


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = safe_next_url(request.values.get("next"))

    if get_current_user() is not None:
        return redirect(next_url or url_for(DEFAULT_ENDPOINT))

    form = {"email": ""}
    errors = {}
    status = 200

    if request.method == "POST":
        form["email"] = normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""

        if not form["email"]:
            errors["email"] = "Please enter your email."
        if not password:
            errors["password"] = "Please enter your password."

        if errors:
            status = 422
        else:
            user = User.query.filter_by(email=form["email"]).first()
            if not _verify_password(user, password):
                flash(INVALID_CREDENTIALS_MESSAGE, "error")
                status = 401
            elif user.is_banned:
                flash(SUSPENDED_MESSAGE, "error")
                status = 403
            else:
                _log_in(user)
                flash(f"Welcome back, {user.name}.", "success")
                return redirect(next_url or url_for(DEFAULT_ENDPOINT))

    return render_template("login.html", form=form, errors=errors, next_url=next_url), status


@bp.route("/logout", methods=["POST"])
def logout():
    # POST only (and CSRF-protected), so another site cannot log users out
    # with a link or image.
    session.clear()
    g.current_user = None
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/account")
@login_required
def account():
    return render_template("account.html", user=g.current_user)


# --------------------------------------------------------------------------
# Template context
# --------------------------------------------------------------------------

def _url_if_exists(endpoint):
    return url_for(endpoint) if endpoint in current_app.view_functions else None


@bp.app_context_processor
def inject_auth_context():
    try:
        user = get_current_user()
    except SQLAlchemyError:
        # Keep error pages renderable when the database is unreachable.
        db.session.rollback()
        user = None

    nav_items = []
    if user is not None:
        nav_items = [
            {"label": label, "endpoint": endpoint, "url": _url_if_exists(endpoint)}
            for label, endpoint, min_role in NAV_ITEMS
            if user.has_role(min_role)
        ]
    return {
        "current_user": user,
        "nav_items": nav_items,
        "search_url": _url_if_exists(SEARCH_ENDPOINT),
    }
