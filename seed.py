"""
Create missing NoteShare tables and insert development seed data.

    python seed.py

Safe to run repeatedly: records are looked up by their unique key (user email,
subject code) and only missing ones are inserted. Existing rows — including
the seed accounts themselves — are never modified, dropped or deleted, so a
password you changed on a seed account is kept.

The passwords below are for LOCAL DEVELOPMENT ONLY. Never use them, or this
script, against a production database.
"""

import sys

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.security import generate_password_hash

from app import create_app
from config import ConfigError
from models import Subject, User, db

SEED_USERS = [
    {"label": "Admin", "name": "Meera Iyer", "email": "admin@noteshare.example.com",
     "password": "AdminDev#2026", "role": "admin", "branch": None, "year": None},
    {"label": "Moderator", "name": "Rahul Verma", "email": "moderator@noteshare.example.com",
     "password": "ModDev#2026", "role": "moderator", "branch": None, "year": None},
    {"label": "Student 1", "name": "Ananya Reddy", "email": "student1@noteshare.example.com",
     "password": "Student1Dev#2026", "role": "student",
     "branch": "Computer Science and Engineering", "year": 3},
    {"label": "Student 2", "name": "Karthik Menon", "email": "student2@noteshare.example.com",
     "password": "Student2Dev#2026", "role": "student",
     "branch": "Computer Science and Engineering", "year": 3},
    {"label": "Student 3", "name": "Sneha Patil", "email": "student3@noteshare.example.com",
     "password": "Student3Dev#2026", "role": "student",
     "branch": "Information Technology", "year": 3},
]

SEED_SUBJECTS = [
    {"code": "CS501", "name": "Design and Analysis of Algorithms", "semester": 5},
    {"code": "CS502", "name": "Computer Networks", "semester": 5},
    {"code": "CS503", "name": "Database Management Systems", "semester": 5},
    {"code": "CS601", "name": "Machine Learning", "semester": 6},
    {"code": "CS602", "name": "Cloud Computing", "semester": 6},
    {"code": "CS603", "name": "Cyber Security", "semester": 6},
]

# MySQL client error codes worth explaining in plain language.
MYSQL_HINTS = {
    1045: "Access denied. Check the user name and password in DATABASE_URL "
          "(special characters in the password must be percent-encoded).",
    1044: "The MySQL user has no access to this database. Run the GRANT statement from README.md.",
    1049: "The database does not exist. Create it first: "
          "CREATE DATABASE noteshare CHARACTER SET utf8mb4;",
    1142: "The MySQL user lacks a required privilege (e.g. CREATE). Run the GRANT statement from README.md.",
    2003: "Cannot reach the MySQL server. Is it running, and are the host and port in DATABASE_URL correct?",
    2005: "Unknown MySQL host. Check the host name in DATABASE_URL.",
}


def seed_users():
    created = 0
    for spec in SEED_USERS:
        user = User.query.filter_by(email=spec["email"]).first()
        if user is None:
            db.session.add(User(
                name=spec["name"],
                email=spec["email"],
                password_hash=generate_password_hash(spec["password"]),
                role=spec["role"],
                branch=spec["branch"],
                year=spec["year"],
                warnings=0,
                is_banned=False,
            ))
            created += 1
        elif user.role != spec["role"]:
            print(f"  Warning: {spec['email']} already exists with role '{user.role}' "
                  f"(expected '{spec['role']}'); left unchanged.")
    return created


def seed_subjects():
    created = 0
    for spec in SEED_SUBJECTS:
        if Subject.query.filter_by(code=spec["code"]).first() is None:
            db.session.add(Subject(**spec))
            created += 1
    return created


def verify():
    """Re-read the seed records from MySQL and confirm the expected shape."""
    emails = [u["email"] for u in SEED_USERS]
    users = User.query.filter(User.email.in_(emails)).all()
    roles = sorted(u.role for u in users)
    expected_roles = sorted(u["role"] for u in SEED_USERS)

    codes = [s["code"] for s in SEED_SUBJECTS]
    subjects = Subject.query.filter(Subject.code.in_(codes)).all()
    per_semester = {sem: sum(1 for s in subjects if s.semester == sem) for sem in (5, 6)}

    problems = []
    if len(users) != len(SEED_USERS) or roles != expected_roles:
        problems.append(f"expected {len(SEED_USERS)} seed users with roles {expected_roles}, "
                        f"found {len(users)} with roles {roles}")
    if len(subjects) != len(SEED_SUBJECTS) or per_semester != {5: 3, 6: 3}:
        problems.append(f"expected 6 seed subjects (3 in semester 5, 3 in semester 6), "
                        f"found {len(subjects)} {per_semester}")
    return len(users), len(subjects), problems


def print_credentials():
    print()
    print("Development test accounts (LOCAL DEVELOPMENT ONLY - never reuse in production)")
    print("-" * 78)
    for spec in SEED_USERS:
        print(f"{spec['label']}:")
        print(f"  Email:    {spec['email']}")
        print(f"  Password: {spec['password']}")
    print()
    print("Accounts that already existed were not modified; if you changed one of these")
    print("passwords yourself, the value above no longer applies to that account.")


def main() -> int:
    print("NoteShare database initialization")
    print("=" * 78, flush=True)  # keep ordering with messages sent to stderr

    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 1

    with app.app_context():
        try:
            version = db.session.execute(text("SELECT VERSION()")).scalar()
            print(f"Database connection: successful (MySQL server {version})")

            db.create_all()  # creates only tables that do not exist yet
            print("Tables: created/verified (users, subjects, notes, ratings, reports)")

            new_users = seed_users()
            new_subjects = seed_subjects()
            db.session.commit()

            user_count, subject_count, problems = verify()
            print(f"Users: {user_count} verified ({new_users} created this run)")
            print(f"Subjects: {subject_count} verified ({new_subjects} created this run)")
            if problems:
                for p in problems:
                    print(f"Verification failed: {p}", file=sys.stderr)
                return 1
        except OperationalError as exc:
            db.session.rollback()
            code = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
            print(f"Database error ({code}): {exc.orig}", file=sys.stderr)
            if code in MYSQL_HINTS:
                print(f"Hint: {MYSQL_HINTS[code]}", file=sys.stderr)
            print("No changes were committed.", file=sys.stderr)
            return 1
        except SQLAlchemyError as exc:
            db.session.rollback()
            print(f"Database error: {exc}", file=sys.stderr)
            print("No changes were committed.", file=sys.stderr)
            return 1
        finally:
            db.session.remove()
            db.engine.dispose()

    print_credentials()
    return 0


if __name__ == "__main__":
    sys.exit(main())
