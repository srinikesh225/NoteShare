"""
Search-engine and sharing support: robots.txt, sitemap.xml, llms.txt,
favicon.ico, absolute URLs for canonical/Open Graph tags, and the subject
links shown in the footer.

Indexing policy
---------------
- Indexed: the browse page (optionally filtered by semester and/or subject,
  which gives one listing page per subject) and active note pages.
- Not indexed (robots "noindex"): searches (?q=), non-default sort orders,
  account pages, upload, My Notes, error pages and non-active notes.
"""

from flask import (Blueprint, Response, current_app, render_template, request,
                   send_from_directory, url_for)
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models import Note, Subject, db

bp = Blueprint("seo", __name__)


def site_root():
    """https://example.org (no trailing slash): SITE_URL, else this request's host."""
    return current_app.config.get("SITE_URL") or request.url_root.rstrip("/")


def absolute_url(path):
    return site_root() + path


@bp.app_context_processor
def inject_seo_context():
    try:
        subjects = Subject.query.order_by(Subject.semester, Subject.code).all()
    except SQLAlchemyError:
        db.session.rollback()  # keep error pages renderable without the database
        subjects = []
    return {
        "absolute_url": absolute_url,
        "footer_subjects": subjects,
        "footer_semesters": sorted({s.semester for s in subjects}),
    }


@bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /upload",
        "Disallow: /my-notes",
        "Disallow: /account",
        "Disallow: /logout",
        "Disallow: /note/*/download",
        "",
        f"Sitemap: {absolute_url(url_for('seo.sitemap_xml'))}",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap_xml():
    notes = db.session.execute(
        db.select(Note.id, Note.upload_date)
        .where(Note.status == "active")
        .order_by(Note.id)
    ).all()
    # Subjects that have at least one active note, with their newest upload.
    subject_rows = db.session.execute(
        db.select(Subject.id, func.max(Note.upload_date))
        .join(Note, Note.subject_id == Subject.id)
        .where(Note.status == "active")
        .group_by(Subject.id)
        .order_by(Subject.id)
    ).all()

    newest = max((n.upload_date for n in notes), default=None)
    entries = [(absolute_url(url_for("notes.browse")), newest)]
    entries += [(absolute_url(url_for("notes.browse", subject=sid)), last) for sid, last in subject_rows]
    entries += [(absolute_url(url_for("notes.detail", note_id=n.id)), n.upload_date) for n in notes]
    entries.append((absolute_url(url_for("auth.register")), None))

    xml = render_template("sitemap.xml", entries=entries)
    return Response(xml, mimetype="application/xml")


@bp.route("/llms.txt")
def llms_txt():
    subjects = Subject.query.order_by(Subject.semester, Subject.code).all()
    text = render_template("llms.txt", subjects=subjects)
    return Response(text, mimetype="text/plain")


@bp.route("/favicon.ico")
def favicon_ico():
    # Browsers and crawlers request /favicon.ico directly.
    return send_from_directory(current_app.static_folder, "favicon.ico",
                               mimetype="image/vnd.microsoft.icon", max_age=60 * 60 * 24 * 7)
