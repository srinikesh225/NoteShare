"""
Load sample notes and ratings for a live demo.

    python demo_seed.py

This fills the Browse page with a few realistic notes so the demo does not
start from an empty screen. It uses the accounts and subjects that seed.py
already created (run `python seed.py` first), and it is safe to run again:
a note is only added if one with the same title does not already exist.

It writes to the database named by DATABASE_URL and creates small, valid
files in UPLOAD_FOLDER so the Download button works during the demo.

This is for demos and local development only, never for real data.
"""

import os
import struct
import sys
import uuid
import zlib

from app import create_app
from config import ConfigError
from models import Note, Rating, Subject, User, db

# (subject code, title, description, file type, uploader email, [(rater email, stars, comment)])
DEMO_NOTES = [
    ("CS501", "Graph Algorithms: BFS, DFS and Shortest Paths",
     "Covers breadth-first and depth-first search, Dijkstra's algorithm and minimum "
     "spanning trees, with worked examples from the Unit 3 lectures.", "pdf",
     "student1@noteshare.example.com", [
         ("student2@noteshare.example.com", 5, "Really clear diagrams, helped me before the test."),
         ("student3@noteshare.example.com", 4, "Good notes, could use a few more examples."),
     ]),
    ("CS501", "Dynamic Programming Cheat Sheet",
     "One-page summary of the common DP patterns: knapsack, longest common subsequence "
     "and matrix chain multiplication.", "pdf",
     "student2@noteshare.example.com", [
         ("student1@noteshare.example.com", 5, "Perfect for last-minute revision."),
     ]),
    ("CS502", "TCP and UDP Revision Notes",
     "Transport-layer summary: the three-way handshake, flow and congestion control, and "
     "when to use UDP instead.", "docx",
     "student3@noteshare.example.com", [
         ("student1@noteshare.example.com", 4, "Nice summary of congestion control."),
         ("student2@noteshare.example.com", 4, ""),
     ]),
    ("CS503", "SQL Joins and Normalization",
     "Inner, outer and self joins with examples, then normal forms up to BCNF with a "
     "step-by-step decomposition.", "pptx",
     "student1@noteshare.example.com", [
         ("student3@noteshare.example.com", 5, "The normalization example finally made it click."),
     ]),
    ("CS601", "Regression and Classification Basics",
     "Linear and logistic regression, decision trees, and how to read a confusion matrix.",
     "png", "student2@noteshare.example.com", []),
    ("CS602", "Virtualization and Cloud Service Models",
     "Hypervisors versus containers, and the difference between IaaS, PaaS and SaaS with "
     "real examples.", "pdf",
     "student3@noteshare.example.com", [
         ("student1@noteshare.example.com", 3, "Decent overview but a bit short."),
         ("student2@noteshare.example.com", 4, "Good for exam prep."),
     ]),
]


def make_pdf(text):
    """A minimal, valid one-page PDF so the download opens in a reader."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_office(main_part, content_type):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                         f'package/2006/content-types"><Override PartName="/{main_part}" '
                         f'ContentType="{content_type}"/></Types>')
        archive.writestr(main_part, '<?xml version="1.0"?><root/>')
    return buffer.getvalue()


def make_png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00" + b"\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def file_bytes(file_type, title):
    if file_type == "pdf":
        return make_pdf(title)
    if file_type == "docx":
        return make_office("word/document.xml",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
    if file_type == "pptx":
        return make_office("ppt/presentation.xml",
                           "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")
    return make_png()


def main():
    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 1

    with app.app_context():
        folder = app.config["UPLOAD_FOLDER"]
        os.makedirs(folder, exist_ok=True)

        users = {u.email: u for u in User.query.all()}
        subjects = {s.code: s for s in Subject.query.all()}
        missing = [spec[4] for spec in DEMO_NOTES if spec[4] not in users]
        if missing:
            print("These accounts are missing; run 'python seed.py' first:", file=sys.stderr)
            for email in sorted(set(missing)):
                print(f"  - {email}", file=sys.stderr)
            return 1

        created = skipped = 0
        try:
            for code, title, description, file_type, uploader_email, ratings in DEMO_NOTES:
                if Note.query.filter_by(title=title).first() is not None:
                    skipped += 1
                    continue
                subject = subjects.get(code)
                if subject is None:
                    print(f"  Skipping '{title}': subject {code} does not exist.", file=sys.stderr)
                    continue

                stored_name = f"{uuid.uuid4().hex}.{file_type}"
                with open(os.path.join(folder, stored_name), "wb") as handle:
                    handle.write(file_bytes(file_type, title))

                note = Note(title=title, description=description, file_path=stored_name,
                            subject_id=subject.id, uploader_id=users[uploader_email].id, status="active")
                db.session.add(note)
                db.session.flush()
                for rater_email, stars, comment in ratings:
                    if rater_email in users:
                        db.session.add(Rating(note_id=note.id, student_id=users[rater_email].id,
                                              stars=stars, comment=comment or None))
                db.session.flush()
                note.update_avg_rating()
                created += 1

            db.session.commit()
        except Exception as exc:  # noqa: BLE001 - demo helper: report and stop
            db.session.rollback()
            print(f"Could not load demo data: {exc}", file=sys.stderr)
            return 1

        total = Note.query.filter_by(status="active").count()
        print("Demo data loaded.")
        print(f"  Notes added this run: {created}")
        print(f"  Already present (skipped): {skipped}")
        print(f"  Active notes now on the Browse page: {total}")
        print("\nStart the app with 'python app.py' and open http://127.0.0.1:5000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
