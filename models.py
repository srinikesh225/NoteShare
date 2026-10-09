"""
SQLAlchemy models for NoteShare.

`db` is created here without an application; `app.create_app()` binds it to
the Flask app with `db.init_app(app)`. This keeps imports one-directional
(app -> models, seed -> app + models) and avoids circular imports.

Timestamps
----------
MySQL's DATETIME type has no time zone. NoteShare therefore stores every
timestamp as UTC: the database default is UTC_TIMESTAMP(), and the UTCDateTime
type below converts aware datetimes to UTC on the way in and returns aware
(tzinfo=UTC) datetimes on the way out. Convert to local time only for display.

Deletion policy
---------------
- Users are never meant to be hard-deleted; ban them with `is_banned`.
  Every foreign key that points at `users` is ON DELETE RESTRICT, so MySQL
  refuses to delete a user who has uploaded, rated or reported anything.
- Subjects are ON DELETE RESTRICT for the same reason: deleting a subject
  must not silently delete the notes filed under it.
- Notes are normally hidden by setting `status = 'removed'`. If a note row is
  hard-deleted, its ratings and reports are deleted with it (ON DELETE
  CASCADE), because they have no meaning without the note.
"""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import TypeDecorator

db = SQLAlchemy()

USER_ROLES = ("student", "moderator", "admin")
# Role hierarchy: each role includes every permission of the roles below it,
# so an admin can do everything a moderator can, and a moderator everything a
# student can. Used by User.has_role() and auth.role_required().
ROLE_LEVELS = {"student": 1, "moderator": 2, "admin": 3}
NOTE_STATUSES = ("active", "flagged", "removed")
REPORT_STATUSES = ("open", "resolved")

# MySQL 8.0.13+ allows expression defaults; this keeps raw-SQL inserts UTC too.
UTC_NOW_DEFAULT = db.text("(UTC_TIMESTAMP())")


class UTCDateTime(TypeDecorator):
    """DATETIME column that always stores UTC and returns aware datetimes."""

    impl = db.DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime given; use datetime.now(timezone.utc).")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def _enum(values, name):
    # Native MySQL ENUM. validate_strings=True also rejects bad values in
    # Python before they reach the database.
    return db.Enum(*values, name=name, validate_strings=True)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.UniqueConstraint("email", name="uq_users_email"),
        db.CheckConstraint("warnings >= 0", name="ck_users_warnings_non_negative"),
        db.CheckConstraint("year IS NULL OR year BETWEEN 1 AND 6", name="ck_users_year_range"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    # Werkzeug hashes (scrypt / pbkdf2) are ~100-170 characters long.
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(_enum(USER_ROLES, "user_role"), nullable=False,
                     default="student", server_default="student")
    branch = db.Column(db.String(100), nullable=True)
    year = db.Column(db.SmallInteger, nullable=True)
    warnings = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    is_banned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(UTCDateTime, nullable=False, server_default=UTC_NOW_DEFAULT)

    # passive_deletes="all": the ORM never tries to null out or delete these
    # rows itself; the RESTRICT foreign keys in MySQL decide (see module doc).
    uploaded_notes = db.relationship("Note", back_populates="uploader", passive_deletes="all")
    ratings = db.relationship("Rating", back_populates="student", passive_deletes="all")
    reports = db.relationship("Report", back_populates="reporter", passive_deletes="all")

    def has_role(self, required_role: str) -> bool:
        """True if this user's role is `required_role` or a higher one."""
        return ROLE_LEVELS.get(self.role, 0) >= ROLE_LEVELS[required_role]

    def __repr__(self):
        return f"<User {self.id} {self.email} ({self.role})>"


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (
        db.UniqueConstraint("code", name="uq_subjects_code"),
        db.CheckConstraint("semester BETWEEN 1 AND 12", name="ck_subjects_semester_range"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    semester = db.Column(db.SmallInteger, nullable=False)

    notes = db.relationship("Note", back_populates="subject", passive_deletes="all")

    def __repr__(self):
        return f"<Subject {self.code} (sem {self.semester})>"


class Note(db.Model):
    __tablename__ = "notes"
    __table_args__ = (
        db.Index("ix_notes_subject_id", "subject_id"),
        db.Index("ix_notes_uploader_id", "uploader_id"),
        db.Index("ix_notes_status", "status"),
        db.CheckConstraint("avg_rating BETWEEN 0 AND 5", name="ck_notes_avg_rating_range"),
        db.CheckConstraint("download_count >= 0", name="ck_notes_download_count_non_negative"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Path of the uploaded file relative to UPLOAD_FOLDER; the file itself
    # lives on disk, never in the database.
    file_path = db.Column(db.String(500), nullable=False)
    subject_id = db.Column(
        db.Integer,
        db.ForeignKey("subjects.id", name="fk_notes_subject", ondelete="RESTRICT"),
        nullable=False,
    )
    uploader_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", name="fk_notes_uploader", ondelete="RESTRICT"),
        nullable=False,
    )
    upload_date = db.Column(UTCDateTime, nullable=False, server_default=UTC_NOW_DEFAULT)
    # DOUBLE rather than MySQL's single-precision FLOAT.
    avg_rating = db.Column(db.Double, nullable=False, default=0.0, server_default="0")
    download_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    status = db.Column(_enum(NOTE_STATUSES, "note_status"), nullable=False,
                       default="active", server_default="active")

    subject = db.relationship("Subject", back_populates="notes")
    uploader = db.relationship("User", back_populates="uploaded_notes")
    ratings = db.relationship("Rating", back_populates="note",
                              cascade="all, delete-orphan", passive_deletes=True)
    reports = db.relationship("Report", back_populates="note",
                              cascade="all, delete-orphan", passive_deletes=True)

    def update_avg_rating(self) -> float:
        """Recalculate `avg_rating` from this note's ratings and return it.

        The average is computed by MySQL (AVG over the ratings table) rather
        than from the in-memory `self.ratings` list, so it is correct even if
        that list is stale. Because the session autoflushes before the query,
        ratings that were just added, changed or deleted in the current
        session are included.

        The result is rounded to 2 decimal places; a note with no ratings
        gets 0.0.

        This method does NOT commit. The caller must call
        `db.session.commit()`, normally in the same transaction as the rating
        change that triggered the recalculation.
        """
        average = (
            db.session.query(db.func.avg(Rating.stars))
            .filter(Rating.note_id == self.id)
            .scalar()
        )
        self.avg_rating = round(float(average), 2) if average is not None else 0.0
        return self.avg_rating

    def __repr__(self):
        return f"<Note {self.id} {self.title!r} ({self.status})>"


class Rating(db.Model):
    __tablename__ = "ratings"
    __table_args__ = (
        # One rating per student per note. This index also serves lookups
        # by note_id, so note_id needs no separate index.
        db.UniqueConstraint("note_id", "student_id", name="uq_ratings_note_student"),
        db.Index("ix_ratings_student_id", "student_id"),
        db.CheckConstraint("stars BETWEEN 1 AND 5", name="ck_ratings_stars_range"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    note_id = db.Column(
        db.Integer,
        db.ForeignKey("notes.id", name="fk_ratings_note", ondelete="CASCADE"),
        nullable=False,
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", name="fk_ratings_student", ondelete="RESTRICT"),
        nullable=False,
    )
    stars = db.Column(db.SmallInteger, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    date = db.Column(UTCDateTime, nullable=False, server_default=UTC_NOW_DEFAULT)

    note = db.relationship("Note", back_populates="ratings")
    student = db.relationship("User", back_populates="ratings")

    def __repr__(self):
        return f"<Rating note={self.note_id} student={self.student_id} stars={self.stars}>"


class Report(db.Model):
    __tablename__ = "reports"
    __table_args__ = (
        # One report per reporter per note. Also serves lookups by note_id.
        db.UniqueConstraint("note_id", "reporter_id", name="uq_reports_note_reporter"),
        db.Index("ix_reports_reporter_id", "reporter_id"),
        db.Index("ix_reports_status", "status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    note_id = db.Column(
        db.Integer,
        db.ForeignKey("notes.id", name="fk_reports_note", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", name="fk_reports_reporter", ondelete="RESTRICT"),
        nullable=False,
    )
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(_enum(REPORT_STATUSES, "report_status"), nullable=False,
                       default="open", server_default="open")
    action_taken = db.Column(db.Text, nullable=True)
    date = db.Column(UTCDateTime, nullable=False, server_default=UTC_NOW_DEFAULT)

    note = db.relationship("Note", back_populates="reports")
    reporter = db.relationship("User", back_populates="reports")

    def __repr__(self):
        return f"<Report note={self.note_id} reporter={self.reporter_id} ({self.status})>"
