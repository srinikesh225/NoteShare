"""
Moderation dashboard and actions. Moderators and admins only (admins inherit
moderator permissions through the role hierarchy).

GET  /moderation                         open reports, grouped by note
GET  /moderation/users                   students: warnings, bans, uploads
POST /moderation/users/<id>/unban        is_banned = False
POST /moderation/users/<id>/reset-warnings   warnings = 0
POST /moderation/note/<id>/dismiss       resolve open reports; flagged -> active
POST /moderation/note/<id>/remove        resolve open reports; note -> removed
POST /moderation/note/<id>/warn          uploader.warnings + 1; ban at the limit
POST /moderation/note/<id>/ban           uploader.is_banned = True

Nothing here deletes notes, files, ratings, reports or users. Every action
locks the note row, changes everything it needs in one transaction, and
records what happened (who, when) in Report.action_taken.
"""

from collections import defaultdict
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import case, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from auth import role_required
from models import Note, Report, User, db
from notes import STATUS_LABELS, lock_note

bp = Blueprint("moderation", __name__, url_prefix="/moderation")

GROUPS_PER_PAGE = 10


def _page_arg(source):
    value = (source.get("page") or "").strip()
    return int(value) if value.isdigit() and 0 < len(value) < 7 and int(value) > 0 else 1


@bp.route("")
@role_required("moderator")
def reports():
    page = _page_arg(request.args)

    # One row per note that has open reports: how many, and the oldest date.
    open_reports = (
        db.select(Report.note_id.label("note_id"),
                  db.func.count(Report.id).label("open_count"),
                  db.func.min(Report.date).label("oldest"))
        .where(Report.status == "open")
        .group_by(Report.note_id)
        .subquery()
    )
    query = (
        db.select(Note)
        .join(open_reports, open_reports.c.note_id == Note.id)
        .options(joinedload(Note.subject), joinedload(Note.uploader))
        # Flagged notes first, then the most-reported, then the longest-waiting.
        .order_by(case((Note.status == "flagged", 0), else_=1),
                  open_reports.c.open_count.desc(),
                  open_reports.c.oldest.asc(),
                  Note.id.asc())
    )
    pagination = db.paginate(query, page=page, per_page=GROUPS_PER_PAGE, error_out=False)
    if pagination.pages and page > pagination.pages:
        return redirect(url_for("moderation.reports", page=pagination.pages))

    # All open reports for the notes on this page, in one query.
    reports_by_note = defaultdict(list)
    note_ids = [note.id for note in pagination.items]
    if note_ids:
        rows = db.session.execute(
            db.select(Report)
            .options(joinedload(Report.reporter))
            .where(Report.note_id.in_(note_ids), Report.status == "open")
            .order_by(Report.date.asc(), Report.id.asc())
        ).scalars().all()
        for report in rows:
            reports_by_note[report.note_id].append(report)

    return render_template(
        "moderation.html",
        pagination=pagination,
        groups=[(note, reports_by_note[note.id]) for note in pagination.items],
        status_labels=STATUS_LABELS,
        ban_at=current_app.config["BAN_AT_WARNINGS"],
        page=pagination.page,
    )


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def _log_line(text):
    moderator = g.current_user
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{stamp}: {text} by {moderator.role} {moderator.name} (user #{moderator.id})"


def _open_reports_locked(note_id):
    return db.session.execute(
        db.select(Report).where(Report.note_id == note_id, Report.status == "open")
        .with_for_update()
    ).scalars().all()


def _record(reports, text, resolve):
    """Append the action to each open report's history; optionally resolve it."""
    line = _log_line(text)
    for report in reports:
        report.action_taken = f"{report.action_taken}\n{line}" if report.action_taken else line
        if resolve:
            report.status = "resolved"


def _back_to_dashboard():
    return redirect(url_for("moderation.reports", page=_page_arg(request.form)))


def _commit_or_fail(note_id, action):
    try:
        db.session.commit()
        return True
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Moderation action %r failed for note %s", action, note_id)
        flash("Something went wrong and nothing was changed. Please try again.", "error")
        return False


def _locked_note_or_404(note_id):
    note = lock_note(note_id)
    if note is None:
        abort(404)
    return note


def _can_act_on(uploader):
    """Moderators can act on students and moderators; only admins on admins."""
    if g.current_user.has_role(uploader.role):
        return True
    flash(f"Only an administrator can warn or suspend this {uploader.role}.", "error")
    return False


@bp.route("/note/<int:note_id>/dismiss", methods=["POST"])
@role_required("moderator")
def dismiss(note_id):
    note = _locked_note_or_404(note_id)
    reports = _open_reports_locked(note.id)
    _record(reports, "Dismissed", resolve=True)
    reactivated = note.status == "flagged"
    if reactivated:
        note.status = "active"  # a removed note stays removed
    if not _commit_or_fail(note_id, "dismiss"):
        return _back_to_dashboard()

    if not reports and not reactivated:
        flash("There were no open reports for this note.", "info")
    else:
        message = f"Dismissed {len(reports)} report{'s' if len(reports) != 1 else ''}."
        if reactivated:
            message += " The note is visible to students again."
        flash(message, "success")
    return _back_to_dashboard()


@bp.route("/note/<int:note_id>/remove", methods=["POST"])
@role_required("moderator")
def remove(note_id):
    note = _locked_note_or_404(note_id)
    reports = _open_reports_locked(note.id)
    _record(reports, "Note removed", resolve=True)
    note.status = "removed"  # the note row, file, ratings and reports are kept
    if not _commit_or_fail(note_id, "remove"):
        return _back_to_dashboard()
    flash(f"“{note.title}” has been removed and is hidden from students. "
          f"{len(reports)} open report{'s were' if len(reports) != 1 else ' was'} closed.", "success")
    return _back_to_dashboard()


@bp.route("/note/<int:note_id>/warn", methods=["POST"])
@role_required("moderator")
def warn(note_id):
    note = _locked_note_or_404(note_id)
    uploader = note.uploader  # always the note's real uploader, never form data
    if not _can_act_on(uploader):
        db.session.rollback()
        return _back_to_dashboard()

    # The form carries the warning count the moderator saw. The UPDATE only
    # applies if it is still the same, so a double-click or a resubmitted form
    # cannot add a second warning by accident.
    seen = (request.form.get("warnings_seen") or "").strip()
    applied = 0
    if seen.isdigit() and len(seen) < 6:
        applied = db.session.execute(
            update(User)
            .where(User.id == uploader.id, User.warnings == int(seen))
            .values(warnings=User.warnings + 1)
            .execution_options(synchronize_session=False)
        ).rowcount
    if applied != 1:
        db.session.rollback()
        flash("This uploader's warning count changed after the page was loaded, so no warning "
              "was added. Check the current count and try again.", "warning")
        return _back_to_dashboard()

    db.session.refresh(uploader)
    limit = current_app.config["BAN_AT_WARNINGS"]
    banned_now = uploader.warnings >= limit and not uploader.is_banned
    if banned_now:
        uploader.is_banned = True
    text = f"Uploader {uploader.name} warned ({uploader.warnings} of {limit})"
    if banned_now:
        text += " and automatically suspended"
    _record(_open_reports_locked(note.id), text, resolve=False)
    if not _commit_or_fail(note_id, "warn"):
        return _back_to_dashboard()

    if banned_now:
        flash(f"{uploader.name} received warning {uploader.warnings} of {limit} and has been "
              "suspended automatically.", "success")
    else:
        flash(f"{uploader.name} has been warned. Warning count: {uploader.warnings} of {limit}.",
              "success")
    return _back_to_dashboard()


@bp.route("/note/<int:note_id>/ban", methods=["POST"])
@role_required("moderator")
def ban(note_id):
    note = _locked_note_or_404(note_id)
    uploader = note.uploader
    if not _can_act_on(uploader):
        db.session.rollback()
        return _back_to_dashboard()
    if uploader.is_banned:
        db.session.rollback()
        flash(f"{uploader.name} is already suspended.", "info")
        return _back_to_dashboard()

    uploader.is_banned = True  # the account, its notes and its history are kept
    _record(_open_reports_locked(note.id), f"Uploader {uploader.name} suspended", resolve=False)
    if not _commit_or_fail(note_id, "ban"):
        return _back_to_dashboard()
    flash(f"{uploader.name} has been suspended and can no longer log in.", "success")
    return _back_to_dashboard()


# --------------------------------------------------------------------------
# Users: GET /moderation/users, POST .../unban, POST .../reset-warnings
# --------------------------------------------------------------------------

USERS_PER_PAGE = 25
USER_SEARCH_MAX_LENGTH = 100


def _users_redirect():
    """Back to the users list, keeping the search and page the moderator was on."""
    q = " ".join((request.form.get("q") or "").split())[:USER_SEARCH_MAX_LENGTH]
    return redirect(url_for("moderation.users", q=q or None, page=_page_arg(request.form)))


def _student_or_404(user_id):
    """Only student accounts are managed here; staff accounts are refused."""
    user = db.session.execute(
        db.select(User).where(User.id == user_id).with_for_update()
    ).scalar_one_or_none()
    if user is None or user.role != "student":
        abort(404)
    return user


@bp.route("/users")
@role_required("moderator")
def users():
    q = " ".join((request.args.get("q") or "").split())[:USER_SEARCH_MAX_LENGTH]
    page = _page_arg(request.args)

    uploads = (
        db.select(Note.uploader_id.label("user_id"), db.func.count(Note.id).label("uploads"))
        .group_by(Note.uploader_id)
        .subquery()
    )
    query = (
        db.select(User, db.func.coalesce(uploads.c.uploads, 0))
        .outerjoin(uploads, uploads.c.user_id == User.id)
        .where(User.role == "student")
        .order_by(User.name, User.id)
    )
    if q:
        # % and _ typed by the moderator are matched literally.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(db.or_(User.name.ilike(pattern, escape="\\"),
                                   User.email.ilike(pattern, escape="\\")))

    total = db.session.execute(
        db.select(db.func.count()).select_from(query.order_by(None).subquery())
    ).scalar()
    pages = max(1, -(-total // USERS_PER_PAGE))
    if page > pages:
        return redirect(url_for("moderation.users", q=q or None, page=pages))
    rows = db.session.execute(
        query.limit(USERS_PER_PAGE).offset((page - 1) * USERS_PER_PAGE)
    ).all()

    return render_template(
        "moderation_users.html",
        rows=rows,
        q=q,
        page=page,
        pages=pages,
        total=total,
        ban_at=current_app.config["BAN_AT_WARNINGS"],
    )


@bp.route("/users/<int:user_id>/unban", methods=["POST"])
@role_required("moderator")
def unban(user_id):
    student = _student_or_404(user_id)
    if not student.is_banned:
        db.session.rollback()
        flash(f"{student.name} is not suspended.", "info")
        return _users_redirect()
    student.is_banned = False  # warnings are left as they are (see README)
    if not _commit_or_fail(user_id, "unban"):
        return _users_redirect()
    current_app.logger.info("User %s unbanned by %s #%s", user_id, g.current_user.role, g.current_user.id)
    flash(f"{student.name} has been unbanned and can log in again.", "success")
    return _users_redirect()


@bp.route("/users/<int:user_id>/reset-warnings", methods=["POST"])
@role_required("moderator")
def reset_warnings(user_id):
    student = _student_or_404(user_id)
    if student.warnings == 0:
        db.session.rollback()
        flash(f"{student.name} has no warnings.", "info")
        return _users_redirect()
    previous = student.warnings
    student.warnings = 0  # does not change is_banned
    if not _commit_or_fail(user_id, "reset warnings"):
        return _users_redirect()
    current_app.logger.info("Warnings of user %s reset from %s by %s #%s",
                            user_id, previous, g.current_user.role, g.current_user.id)
    flash(f"{student.name}'s warnings have been reset to 0.", "success")
    return _users_redirect()
