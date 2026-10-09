"""
Small, safe schema upgrades for databases created by an earlier phase.

    python migrate.py

`db.create_all()` creates missing tables but never changes existing ones, so a
database created before a column was added needs that column added here.
Every step checks first and only ADDs things, so running this again (or on a
brand-new database) is harmless. Nothing is ever dropped or deleted.

seed.py and the test suite call apply_migrations() automatically.

Migrations
----------
001 (Phase 4): reports.details — TEXT NULL, the reporter's optional
    explanation. Existing reports keep all their data; their details are
    simply empty (NULL). Equivalent SQL:

        ALTER TABLE reports ADD COLUMN details TEXT NULL AFTER reason;
"""

import sys

from sqlalchemy import text


def _column_exists(connection, table, column):
    return connection.execute(
        text("SELECT COUNT(*) FROM information_schema.COLUMNS "
             "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"),
        {"table": table, "column": column},
    ).scalar() > 0


def apply_migrations(engine):
    """Apply any missing upgrades; return the list of steps that ran."""
    applied = []
    with engine.begin() as connection:
        if not _column_exists(connection, "reports", "details"):
            connection.execute(text("ALTER TABLE reports ADD COLUMN details TEXT NULL AFTER reason"))
            applied.append("001: added reports.details")
    return applied


def main():
    from app import create_app
    from config import ConfigError
    from models import db

    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 1
    with app.app_context():
        db.create_all()
        applied = apply_migrations(db.engine)
    print("\n".join(applied) if applied else "Database schema is already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
