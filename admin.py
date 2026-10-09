"""
Subject administration. Administrators only.

GET       /admin/subjects                    list with note counts
GET, POST /admin/subjects/add                add a subject
GET, POST /admin/subjects/<id>/edit          edit code, name, semester
POST      /admin/subjects/<id>/delete        delete, only if no notes use it

Semester policy: 1 to 8 (a four-year degree). Subject codes are stored in
upper case and must be unique (uq_subjects_code in MySQL).
"""

import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth import role_required
from models import Note, Subject, db

bp = Blueprint("admin", __name__, url_prefix="/admin")

SEMESTERS = range(1, 9)
CODE_MAX_LENGTH = Subject.code.type.length   # 20
NAME_MAX_LENGTH = Subject.name.type.length   # 150
CODE_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9 -]*")
IN_USE_MESSAGE = "This subject cannot be deleted because notes are associated with it."


def _note_count(subject_id):
    return db.session.execute(
        db.select(db.func.count(Note.id)).where(Note.subject_id == subject_id)
    ).scalar()


@bp.route("/subjects")
@role_required("admin")
def subjects():
    rows = db.session.execute(
        db.select(Subject, db.func.count(Note.id))
        .outerjoin(Note, Note.subject_id == Subject.id)
        .group_by(Subject.id)
        .order_by(Subject.semester, Subject.code)
    ).all()
    return render_template("admin_subjects.html", rows=rows)


def _validate(data, current=None):
    form = {
        "code": " ".join((data.get("code") or "").split()).upper(),
        "name": " ".join((data.get("name") or "").split()),
        "semester": (data.get("semester") or "").strip(),
    }
    errors = {}

    if not form["code"]:
        errors["code"] = "Please enter a subject code."
    elif len(form["code"]) > CODE_MAX_LENGTH:
        errors["code"] = f"Code must be {CODE_MAX_LENGTH} characters or fewer."
    elif not CODE_PATTERN.fullmatch(form["code"]):
        errors["code"] = "Use letters, numbers, spaces or hyphens, for example CS501."
    else:
        existing = Subject.query.filter(Subject.code == form["code"]).first()
        if existing is not None and (current is None or existing.id != current.id):
            errors["code"] = f"A subject with the code {form['code']} already exists."

    if not form["name"]:
        errors["name"] = "Please enter the subject name."
    elif len(form["name"]) > NAME_MAX_LENGTH:
        errors["name"] = f"Name must be {NAME_MAX_LENGTH} characters or fewer."

    if not (form["semester"].isdigit() and len(form["semester"]) < 3 and int(form["semester"]) in SEMESTERS):
        errors["semester"] = f"Choose a semester from {SEMESTERS[0]} to {SEMESTERS[-1]}."

    return form, errors


def _render_form(form, errors, subject=None, status=200):
    return render_template("admin_subject_form.html", form=form, errors=errors, subject=subject,
                           semesters=SEMESTERS, code_max=CODE_MAX_LENGTH,
                           name_max=NAME_MAX_LENGTH), status


def _save(form, subject, is_new):
    """Commit the subject; return an errors dict (empty on success)."""
    subject.code, subject.name, subject.semester = form["code"], form["name"], int(form["semester"])
    if is_new:
        db.session.add(subject)
    try:
        db.session.commit()
        return {}
    except IntegrityError as exc:
        db.session.rollback()
        orig = getattr(exc, "orig", None)
        if orig and orig.args and orig.args[0] == 1062:  # another admin used the code first
            return {"code": f"A subject with the code {form['code']} already exists."}
        current_app.logger.exception("Could not save subject")
        return {"form": "The subject could not be saved. Please try again."}


@bp.route("/subjects/add", methods=["GET", "POST"])
@role_required("admin")
def add_subject():
    if request.method == "GET":
        return _render_form({"code": "", "name": "", "semester": ""}, {})
    form, errors = _validate(request.form)
    if not errors:
        errors = _save(form, Subject(), is_new=True)
    if errors:
        flash(errors.pop("form", "Please correct the highlighted fields."), "error")
        return _render_form(form, errors, status=422)
    flash(f"Subject {form['code']} added.", "success")
    return redirect(url_for("admin.subjects"))


@bp.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_subject(subject_id):
    subject = db.session.get(Subject, subject_id)
    if subject is None:
        abort(404)
    if request.method == "GET":
        form = {"code": subject.code, "name": subject.name, "semester": str(subject.semester)}
        return _render_form(form, {}, subject)
    form, errors = _validate(request.form, current=subject)
    if not errors:
        errors = _save(form, subject, is_new=False)
    if errors:
        flash(errors.pop("form", "Please correct the highlighted fields."), "error")
        return _render_form(form, errors, db.session.get(Subject, subject_id), status=422)
    # Notes keep pointing at the same subject id, so they are unaffected.
    flash(f"Subject {form['code']} updated.", "success")
    return redirect(url_for("admin.subjects"))


@bp.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@role_required("admin")
def delete_subject(subject_id):
    subject = db.session.get(Subject, subject_id)
    if subject is None:
        abort(404)
    if _note_count(subject.id):
        flash(IN_USE_MESSAGE, "error")
        return redirect(url_for("admin.subjects"))

    code = subject.code
    db.session.delete(subject)
    try:
        db.session.commit()
    except IntegrityError:
        # A note was added to this subject at the same moment; the foreign
        # key (ON DELETE RESTRICT) refused the delete.
        db.session.rollback()
        flash(IN_USE_MESSAGE, "error")
        return redirect(url_for("admin.subjects"))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not delete subject %s", subject_id)
        flash("The subject could not be deleted. Please try again.", "error")
        return redirect(url_for("admin.subjects"))
    flash(f"Subject {code} deleted.", "success")
    return redirect(url_for("admin.subjects"))
