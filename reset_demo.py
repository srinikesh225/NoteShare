"""
Reset the demo back to a clean slate.

    python reset_demo.py

Deletes every note, rating and report, removes their uploaded files, and clears
any warnings and bans on accounts. It does NOT delete users or subjects and does
NOT drop any tables, so `python demo_seed.py` can refill it afterwards.

It asks for confirmation first and works on the database named by DATABASE_URL.
For demos and local development only.
"""

import os
import sys

from app import create_app
from config import ConfigError
from models import Note, Rating, Report, User, db


def main():
    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 1

    with app.app_context():
        from sqlalchemy.engine import make_url
        database = make_url(app.config["SQLALCHEMY_DATABASE_URI"]).database or "(unknown)"
        notes = Note.query.count()
        reports = Report.query.count()
        ratings = Rating.query.count()

        print(f"This will DELETE all demo content from the '{database}' database:")
        print(f"  notes: {notes}, ratings: {ratings}, reports: {reports}")
        print("  and reset warnings/bans on all accounts.")
        print("Users and subjects are kept.")
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was changed.")
            return 0

        # Collect the stored file names before deleting the rows.
        file_names = [name for (name,) in db.session.query(Note.file_path).all()]
        folder = app.config["UPLOAD_FOLDER"]

        try:
            # Reports and ratings first, then notes (also covered by cascade,
            # but explicit keeps it clear). Then clear warnings/bans.
            Report.query.delete()
            Rating.query.delete()
            Note.query.delete()
            User.query.update({User.warnings: 0, User.is_banned: False})
            db.session.commit()
        except Exception as exc:  # noqa: BLE001 - demo helper: report and stop
            db.session.rollback()
            print(f"Could not reset: {exc}", file=sys.stderr)
            return 1

        removed = 0
        for name in file_names:
            path = os.path.join(folder, name)
            try:
                os.remove(path)
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"  Could not remove file {name}: {exc}", file=sys.stderr)

        print("\nDemo reset complete.")
        print(f"  Deleted {notes} notes, {ratings} ratings, {reports} reports.")
        print(f"  Removed {removed} uploaded files.")
        print("  Warnings and bans cleared on all accounts.")
        print("\nRun 'python demo_seed.py' to load the sample notes again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
