"""
Core note features: browse/search, upload, note details, download, My Notes
and deleting your own notes.

Visibility rules
----------------
- Active notes are visible to everyone; downloading requires login.
- Flagged and removed notes are visible (and downloadable) only to their
  uploader and to moderators/admins. Everyone else gets a 404, so hidden
  notes do not reveal that they exist.
- Only a note's uploader can delete it.

File storage
------------
Uploaded files are saved in UPLOAD_FOLDER as "<32 hex chars>.<ext>" (a random
UUID), and Note.file_path stores only that file name, never a path or the
original file name. Files are served only through the download route.
"""

import os
import re
import uuid
import zipfile
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)
from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import contains_eager, joinedload
from werkzeug.utils import secure_filename

from auth import get_current_user, login_required, safe_next_url
from models import Note, Rating, Subject, db

bp = Blueprint("notes", __name__)

PER_PAGE = 12
TITLE_MAX_LENGTH = Note.title.type.length  # 200
DESCRIPTION_MAX_LENGTH = 5000
SEARCH_MAX_LENGTH = 100

SORT_OPTIONS = {
    "newest": "Newest first",
    "highest_rated": "Highest rated",
    "most_downloaded": "Most downloaded",
}
DEFAULT_SORT = "newest"

STATUS_LABELS = {
    "active": "Active",
    "flagged": "Flagged / Under Review",
    "removed": "Removed",
}

FILE_TYPE_LABELS = {"pdf": "PDF", "docx": "Word", "pptx": "PowerPoint", "jpg": "JPG", "png": "PNG"}
FILE_MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "png": "image/png",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _sort_columns(sort):
    # Every ordering ends with Note.id so pages are stable when values tie.
    if sort == "highest_rated":
        return (Note.avg_rating.desc(), Note.upload_date.desc(), Note.id.desc())
    if sort == "most_downloaded":
        return (Note.download_count.desc(), Note.upload_date.desc(), Note.id.desc())
    return (Note.upload_date.desc(), Note.id.desc())


def _int_arg(name):
    """A positive int from the query string, or None for missing/malformed values."""
    value = (request.args.get(name) or "").strip()
    return int(value) if value.isdigit() and len(value) < 10 else None


def _all_subjects():
    return Subject.query.order_by(Subject.semester, Subject.code).all()


def can_view(note, user):
    """Active notes: everyone. Other statuses: the uploader and moderators/admins."""
    if note.status == "active":
        return True
    return user is not None and (user.id == note.uploader_id or user.has_role("moderator"))


def _get_viewable_note_or_404(note_id, *options):
    note = db.session.get(Note, note_id, options=list(options))
    if note is None or not can_view(note, get_current_user()):
        abort(404)
    return note


def _stored_name_pattern():
    extensions = "|".join(sorted(current_app.config["ALLOWED_EXTENSIONS"]))
    return re.compile(rf"[0-9a-f]{{32}}\.(?:{extensions})")


def stored_file_path(note):
    """Absolute path of a note's file inside UPLOAD_FOLDER, or None if the
    stored name is not one this app generates (e.g. '../config.py')."""
    if not _stored_name_pattern().fullmatch(note.file_path or ""):
        return None
    folder = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    path = os.path.realpath(os.path.join(folder, note.file_path))
    if os.path.commonpath([folder, path]) != folder:
        return None
    return path


def file_extension(note):
    return (note.file_path or "").rsplit(".", 1)[-1].lower()


def _download_name(note):
    base = secure_filename(note.title)[:80] or f"note-{note.id}"
    return f"{base}.{file_extension(note)}"


def _stream_size(stream):
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _content_matches_extension(stream, extension):
    """Check the file's leading bytes ("magic numbers") against its extension.

    This catches renamed files (e.g. a .exe renamed to .pdf); it does not prove
    a document is harmless. Uploaded files are never executed or rendered.
    """
    head = stream.read(8)
    stream.seek(0)
    if extension == "pdf":
        return head.startswith(b"%PDF-")
    if extension == "png":
        return head == b"\x89PNG\r\n\x1a\n"
    if extension == "jpg":
        return head.startswith(b"\xff\xd8\xff")
    if extension in ("docx", "pptx"):
        required = "word/document.xml" if extension == "docx" else "ppt/presentation.xml"
        try:
            with zipfile.ZipFile(stream) as archive:
                return required in archive.namelist()
        except zipfile.BadZipFile:
            return False
        finally:
            stream.seek(0)
    return False


def _remove_file_quietly(path, note_id=None):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        current_app.logger.exception(
            "Could not remove stored file %s (note %s); delete it manually",
            os.path.basename(path), note_id)


# --------------------------------------------------------------------------
# Browse: GET /
# --------------------------------------------------------------------------

@bp.route("/")
def browse():
    subjects = _all_subjects()
    subject_ids = {s.id for s in subjects}
    semesters = sorted({s.semester for s in subjects})

    # Malformed or unknown filter values are ignored rather than erroring.
    q = " ".join((request.args.get("q") or "").split())[:SEARCH_MAX_LENGTH]
    semester = _int_arg("semester")
    semester = semester if semester in semesters else None
    subject_id = _int_arg("subject")
    subject_id = subject_id if subject_id in subject_ids else None
    sort = request.args.get("sort") or DEFAULT_SORT
    sort = sort if sort in SORT_OPTIONS else DEFAULT_SORT
    page = max(_int_arg("page") or 1, 1)

    # One query: filters, then ordering, then SQL LIMIT/OFFSET pagination.
    query = (
        db.select(Note)
        .join(Note.subject)
        .join(Note.uploader)
        .options(contains_eager(Note.subject), contains_eager(Note.uploader))
        .where(Note.status == "active")
    )
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(Note.title.ilike(pattern, escape="\\"),
                                Note.description.ilike(pattern, escape="\\")))
    if semester is not None:
        query = query.where(Subject.semester == semester)
    if subject_id is not None:
        query = query.where(Note.subject_id == subject_id)
    query = query.order_by(*_sort_columns(sort))

    pagination = db.paginate(query, page=page, per_page=PER_PAGE, error_out=False)

    # Parameters to carry into pagination links (only those in effect).
    filter_args = {"q": q or None, "semester": semester, "subject": subject_id,
                   "sort": sort if "sort" in request.args or sort != DEFAULT_SORT else None}
    filter_args = {k: v for k, v in filter_args.items() if v is not None}

    if pagination.pages and page > pagination.pages:
        return redirect(url_for("notes.browse", page=pagination.pages, **filter_args))

    # Active-note counts per semester for the semester shortcut links.
    semester_counts = dict(db.session.execute(
        db.select(Subject.semester, db.func.count(Note.id))
        .join(Note, Note.subject_id == Subject.id)
        .where(Note.status == "active")
        .group_by(Subject.semester)
    ).all())

    return render_template(
        "home.html",
        pagination=pagination,
        notes=pagination.items,
        subjects=subjects,
        semesters=semesters,
        semester_counts=semester_counts,
        sort_options=SORT_OPTIONS,
        q=q,
        semester=semester,
        subject_id=subject_id,
        selected_subject=next((s for s in subjects if s.id == subject_id), None),
        sort=sort,
        page=pagination.page,
        filter_args=filter_args,
        has_filters=bool(q or semester or subject_id),
        # Search results and re-sorted lists are not indexed; plain and
        # semester/subject listings are.
        indexable=not q and sort == DEFAULT_SORT,
    )


# --------------------------------------------------------------------------
# Upload: GET/POST /upload
# --------------------------------------------------------------------------

def _validate_upload(subjects_by_id):
    data = request.form
    form = {
        "title": " ".join((data.get("title") or "").split()),
        "description": (data.get("description") or "").replace("\r\n", "\n").strip(),
        "subject_id": (data.get("subject_id") or "").strip(),
    }
    errors = {}

    if not form["title"]:
        errors["title"] = "Please enter a title."
    elif len(form["title"]) > TITLE_MAX_LENGTH:
        errors["title"] = f"Title must be {TITLE_MAX_LENGTH} characters or fewer."

    if len(form["description"]) > DESCRIPTION_MAX_LENGTH:
        errors["description"] = f"Description must be {DESCRIPTION_MAX_LENGTH:,} characters or fewer."

    subject = None
    if not form["subject_id"]:
        errors["subject_id"] = "Please choose a subject."
    else:
        subject = subjects_by_id.get(int(form["subject_id"])) if form["subject_id"].isdigit() else None
        if subject is None:
            errors["subject_id"] = "Choose a subject from the list."

    upload = request.files.get("file")
    extension = None
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if upload is None or not upload.filename:
        errors["file"] = "Please choose a file to upload."
    else:
        # The original name is used only to read its extension.
        extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if extension not in allowed:
            errors["file"] = "This file type isn't allowed. Upload a PDF, DOCX, PPTX, JPG or PNG file."
        elif _stream_size(upload.stream) == 0:
            errors["file"] = "The selected file is empty."
        elif not _content_matches_extension(upload.stream, extension):
            errors["file"] = f"This file doesn't look like a valid .{extension} file."

    if errors and "file" not in errors:
        errors["file"] = "Please choose the file again (browsers clear file fields after an error)."

    return form, errors, subject, upload, extension


def render_upload_form(form=None, errors=None, status=200):
    subjects = _all_subjects()
    return render_template(
        "upload.html",
        form=form or {"title": "", "description": "", "subject_id": ""},
        errors=errors or {},
        subjects=subjects,
        semesters=sorted({s.semester for s in subjects}),
        max_bytes=current_app.config["MAX_CONTENT_LENGTH"],
        accept=",".join(f".{ext}" for ext in sorted(current_app.config["ALLOWED_EXTENSIONS"])),
        description_max=DESCRIPTION_MAX_LENGTH,
        title_max=TITLE_MAX_LENGTH,
    ), status


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "GET":
        return render_upload_form()

    subjects_by_id = {s.id: s for s in _all_subjects()}
    form, errors, subject, upload_file, extension = _validate_upload(subjects_by_id)
    if errors:
        flash("Please correct the highlighted fields.", "error")
        return render_upload_form(form, errors, 422)

    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    path = os.path.join(folder, stored_name)

    try:
        upload_file.save(path)
    except OSError:
        current_app.logger.exception("Could not write uploaded file for user %s", g.current_user.id)
        flash("Your file could not be saved. Please try again.", "error")
        return render_upload_form(form, {"file": "Please choose the file again."}, 500)

    note = Note(
        title=form["title"],
        description=form["description"] or None,
        file_path=stored_name,
        subject_id=subject.id,
        uploader_id=g.current_user.id,  # always the signed-in user, never form data
        avg_rating=0.0,
        download_count=0,
        status="active",
    )
    db.session.add(note)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        _remove_file_quietly(path)
        current_app.logger.exception("Could not save note record for user %s", g.current_user.id)
        flash("Your note could not be saved. Please try again.", "error")
        return render_upload_form(form, {"file": "Please choose the file again."}, 500)

    flash("Your note has been uploaded.", "success")
    return redirect(url_for("notes.detail", note_id=note.id))


# --------------------------------------------------------------------------
# Note details: GET /note/<id>
# --------------------------------------------------------------------------

@bp.route("/note/<int:note_id>")
def detail(note_id):
    note = _get_viewable_note_or_404(note_id, joinedload(Note.subject), joinedload(Note.uploader))

    # Ratings are read from the Rating rows themselves, so the summary on this
    # page can never be stale even if avg_rating has not been recalculated.
    ratings = db.session.execute(
        db.select(Rating)
        .options(joinedload(Rating.student))
        .where(Rating.note_id == note.id)
        .order_by(Rating.date.desc(), Rating.id.desc())
    ).scalars().all()
    rating_count = len(ratings)
    rating_average = round(sum(r.stars for r in ratings) / rating_count, 1) if ratings else None

    # "Back to results" returns to the listing the user came from, if safe.
    back_url = safe_next_url(request.args.get("back"))
    if back_url and urlsplit(back_url).path not in {url_for("notes.browse"), url_for("notes.mine")}:
        back_url = None

    user = get_current_user()
    return render_template(
        "note_detail.html",
        note=note,
        ratings=ratings,
        rating_count=rating_count,
        rating_average=rating_average,
        back_url=back_url,
        is_owner=user is not None and user.id == note.uploader_id,
        status_label=STATUS_LABELS[note.status],
        file_type=FILE_TYPE_LABELS.get(file_extension(note), file_extension(note).upper()),
        file_mime=FILE_MIME_TYPES.get(file_extension(note), "application/octet-stream"),
    )


# --------------------------------------------------------------------------
# Download: GET /note/<id>/download
# --------------------------------------------------------------------------

@bp.route("/note/<int:note_id>/download")
@login_required
def download(note_id):
    note = _get_viewable_note_or_404(note_id)

    path = stored_file_path(note)
    if path is None or not os.path.isfile(path):
        current_app.logger.error("Download failed: file for note %s is missing or has an invalid name",
                                 note.id)
        abort(404, description="The file for this note is unavailable right now. "
                               "Please try again later.")

    # Count the download only once every check has passed and the file is
    # about to be sent. The UPDATE runs in MySQL (download_count + 1), so
    # simultaneous downloads cannot overwrite each other's increments.
    db.session.execute(
        update(Note).where(Note.id == note.id).values(download_count=Note.download_count + 1)
    )
    db.session.commit()

    response = send_from_directory(
        os.path.realpath(current_app.config["UPLOAD_FOLDER"]),
        note.file_path,
        as_attachment=True,
        download_name=_download_name(note),
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# --------------------------------------------------------------------------
# My Notes: GET /my-notes
# --------------------------------------------------------------------------

@bp.route("/my-notes")
@login_required
def mine():
    page = max(_int_arg("page") or 1, 1)
    query = (
        db.select(Note)
        .options(joinedload(Note.subject))
        .where(Note.uploader_id == g.current_user.id)
        .order_by(Note.upload_date.desc(), Note.id.desc())
    )
    pagination = db.paginate(query, page=page, per_page=PER_PAGE, error_out=False)
    if pagination.pages and page > pagination.pages:
        return redirect(url_for("notes.mine", page=pagination.pages))
    return render_template("my_notes.html", pagination=pagination, notes=pagination.items,
                           status_labels=STATUS_LABELS)


# --------------------------------------------------------------------------
# Delete: POST /note/<id>/delete
# --------------------------------------------------------------------------

@bp.route("/note/<int:note_id>/delete", methods=["POST"])
@login_required
def delete(note_id):
    note = _get_viewable_note_or_404(note_id)
    if note.uploader_id != g.current_user.id:
        abort(403)

    path = stored_file_path(note)
    title = note.title

    # Ratings and reports on this note are removed by the ON DELETE CASCADE
    # foreign keys; nothing belonging to other notes is touched.
    db.session.delete(note)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not delete note %s", note_id)
        flash("The note could not be deleted. Please try again.", "error")
        return redirect(url_for("notes.mine"))

    # Remove the file only after the database change is committed, so a
    # failed delete never leaves a note pointing at a missing file.
    if path and os.path.isfile(path):
        _remove_file_quietly(path, note_id)

    flash(f"“{title}” has been deleted.", "success")
    return redirect(url_for("notes.mine"))


@bp.app_template_filter("ui_date")
def ui_date(value):
    return value.strftime("%d %b %Y") if value else ""
