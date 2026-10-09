"""Search, sharing and page-quality checks: titles, headings, descriptions,
canonical links, robots rules, sitemap, llms.txt, structured data and icons."""

import html
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import get_csrf_token, log_in, upload_note
from models import Note, Rating, db

STATIC = Path(__file__).resolve().parent.parent / "static"


def head_value(raw, pattern):
    match = re.search(pattern, raw)
    return html.unescape(match.group(1)) if match else None


def page_facts(response):
    raw = response.get_data(as_text=True)
    return {
        "raw": raw,
        "title": head_value(raw, r"<title>(.*?)</title>"),
        "description": head_value(raw, r'<meta name="description" content="([^"]*)">'),
        "robots": head_value(raw, r'<meta name="robots" content="([^"]*)">'),
        "canonical": head_value(raw, r'<link rel="canonical" href="([^"]*)">'),
        "og_title": head_value(raw, r'<meta property="og:title" content="([^"]*)">'),
        "og_image": head_value(raw, r'<meta property="og:image" content="([^"]*)">'),
        "h1_count": len(re.findall(r"<h1[\s>]", raw)),
        "json_ld": [json.loads(block) for block in
                    re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)],
    }


@pytest.fixture
def site(app, client, make_user, subjects):
    """A signed-in student with one active note (rated) and one flagged note."""
    owner = make_user(email="owner@college.example", name="Asha Kulkarni")
    log_in(client, "owner@college.example", "correct-password")
    assert upload_note(client, "Graph Algorithms Notes", subjects["CS501"],
                       description="BFS, DFS and shortest paths.").status_code == 302
    assert upload_note(client, "Hidden note", subjects["CS502"]).status_code == 302
    rater = make_user(email="rater@college.example", name="Rater")
    with app.app_context():
        active = Note.query.filter_by(title="Graph Algorithms Notes").one()
        hidden = Note.query.filter_by(title="Hidden note").one()
        hidden.status = "flagged"
        db.session.add(Rating(note_id=active.id, student_id=rater, stars=4))
        db.session.flush()
        active.update_avg_rating()
        db.session.commit()
        ids = {"active": active.id, "hidden": hidden.id, "owner": owner, "subjects": subjects}
    # Leave the client signed out; tests sign in when they need private pages.
    client.post("/logout", data={"csrf_token": get_csrf_token(client, "/")})
    return ids


def sign_in_owner(client):
    log_in(client, "owner@college.example", "correct-password")


PUBLIC_PAGES = ["/", "/login", "/register", "/?semester=5"]
PRIVATE_PAGES = ["/upload", "/my-notes", "/account"]


def test_every_page_has_one_h1_title_and_description(app, client, site):
    public = PUBLIC_PAGES + [f"/note/{site['active']}", f"/?subject={site['subjects']['CS501']}",
                             "/no-such-page"]
    private = PRIVATE_PAGES + [f"/note/{site['hidden']}"]  # the hidden note: owner only
    responses = [(path, client.get(path)) for path in public]
    sign_in_owner(client)
    responses += [(path, client.get(path)) for path in private]
    paths = public + private
    titles = set()
    for path, response in responses:
        assert response.status_code in (200, 404), path
        facts = page_facts(response)
        assert facts["h1_count"] == 1, path
        assert facts["title"] and facts["title"].endswith(" · NoteShare"), path
        assert "vite" not in facts["title"].lower() and "react" not in facts["title"].lower()
        assert facts["description"] and len(facts["description"]) > 20, path
        assert facts["og_title"] and facts["og_image"].endswith("/static/og-image.png"), path
        titles.add(facts["title"])
    assert len(titles) == len(paths), "page titles must be unique"


def test_canonical_links(client, site):
    subject_id = site["subjects"]["CS501"]
    assert page_facts(client.get("/"))["canonical"] == "http://localhost/"
    assert page_facts(client.get("/register"))["canonical"] == "http://localhost/register"
    note = page_facts(client.get(f"/note/{site['active']}?back=/%3Fq%3Dx"))
    assert note["canonical"] == f"http://localhost/note/{site['active']}"  # no query string
    listing = page_facts(client.get(f"/?subject={subject_id}&sort=newest&q=graph"))
    assert listing["canonical"] == f"http://localhost/?subject={subject_id}"
    assert page_facts(client.get("/no-such-page"))["canonical"] is None


def test_site_url_setting_controls_absolute_urls(app, client, site):
    app.config["SITE_URL"] = "https://notes.example.edu"
    try:
        facts = page_facts(client.get("/"))
        assert facts["canonical"] == "https://notes.example.edu/"
        assert facts["og_image"] == "https://notes.example.edu/static/og-image.png"
        assert "Sitemap: https://notes.example.edu/sitemap.xml" in client.get("/robots.txt").get_data(as_text=True)
    finally:
        app.config["SITE_URL"] = ""


def test_robots_meta_indexing_policy(client, site):
    for path in ["/", "/register", "/?semester=5", f"/note/{site['active']}"]:
        assert page_facts(client.get(path))["robots"] == "index, follow", path
    for path in ["/login", "/?q=graph", "/?sort=most_downloaded"]:
        assert page_facts(client.get(path))["robots"].startswith("noindex"), path
    sign_in_owner(client)
    for path in PRIVATE_PAGES:
        assert page_facts(client.get(path))["robots"].startswith("noindex"), path
    assert page_facts(client.get(f"/note/{site['hidden']}"))["robots"] == "noindex, nofollow"
    assert page_facts(client.get("/no-such-page"))["robots"] == "noindex, nofollow"


def test_robots_txt(client):
    response = client.get("/robots.txt")
    body = response.get_data(as_text=True)
    assert response.status_code == 200 and response.mimetype == "text/plain"
    for rule in ("User-agent: *", "Disallow: /upload", "Disallow: /my-notes", "Disallow: /account",
                 "Disallow: /note/*/download", "Sitemap: http://localhost/sitemap.xml"):
        assert rule in body


def test_sitemap_lists_only_public_pages(client, site):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200 and response.mimetype == "application/xml"
    root = ET.fromstring(response.data)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in root.findall("s:url/s:loc", ns)]
    assert "http://localhost/" in locs
    assert f"http://localhost/note/{site['active']}" in locs
    assert f"http://localhost/note/{site['hidden']}" not in locs          # flagged
    assert f"http://localhost/?subject={site['subjects']['CS501']}" in locs  # has an active note
    assert f"http://localhost/?subject={site['subjects']['CS502']}" not in locs  # only a flagged note
    assert not any("upload" in loc or "my-notes" in loc or "account" in loc for loc in locs)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", el.text) for el in root.findall("s:url/s:lastmod", ns))


def test_llms_txt(client, site):
    response = client.get("/llms.txt")
    body = response.get_data(as_text=True)
    assert response.status_code == 200 and response.mimetype == "text/plain"
    assert body.startswith("# NoteShare\n\n> ")
    assert "[Browse notes](http://localhost/)" in body
    assert f"(http://localhost/?subject={site['subjects']['CS501']})" in body
    assert "CS603 — Cyber Security" in body


def test_structured_data(client, site):
    home = page_facts(client.get("/"))["json_ld"]
    assert home[0]["@type"] == "WebSite"
    assert home[0]["potentialAction"]["target"]["urlTemplate"] == "http://localhost/?q={search_term_string}"
    assert page_facts(client.get("/?q=graph"))["json_ld"] == []

    resource, crumbs = page_facts(client.get(f"/note/{site['active']}"))["json_ld"]
    assert resource["@type"] == "LearningResource"
    assert resource["name"] == "Graph Algorithms Notes"
    assert resource["author"] == {"@type": "Person", "name": "Asha Kulkarni"}
    assert resource["aggregateRating"]["ratingValue"] == 4.0
    assert resource["aggregateRating"]["ratingCount"] == 1
    assert resource["encodingFormat"] == "application/pdf"
    assert [item["name"] for item in crumbs["itemListElement"]] == [
        "Browse notes", "CS501 Design and Analysis of Algorithms", "Graph Algorithms Notes"]

    # Hidden notes carry no structured data, even for their owner.
    sign_in_owner(client)
    assert page_facts(client.get(f"/note/{site['hidden']}"))["json_ld"] == []


def test_structured_data_escapes_user_text(app, client, site):
    with app.app_context():
        db.session.get(Note, site["active"]).title = "</script><script>alert(1)</script>"
        db.session.commit()
    raw = client.get(f"/note/{site['active']}").get_data(as_text=True)
    assert "</script><script>alert(1)" not in raw
    resource = page_facts(client.get(f"/note/{site['active']}"))["json_ld"][0]
    assert resource["name"] == "</script><script>alert(1)</script>"


def test_breadcrumbs_and_internal_links_on_note_page(client, site):
    raw = client.get(f"/note/{site['active']}").get_data(as_text=True)
    crumbs = raw[raw.index('aria-label="Breadcrumb"'):raw.index("</nav>", raw.index('aria-label="Breadcrumb"'))]
    assert 'href="/">Browse notes</a>' in crumbs
    assert f'href="/?subject={site["subjects"]["CS501"]}">CS501 Design and Analysis of Algorithms</a>' in crumbs
    assert '<span aria-current="page">Graph Algorithms Notes</span>' in crumbs
    assert 'href="/?semester=5">Semester 5</a>' in raw


def test_footer_links_every_subject(client, site):
    raw = client.get("/login").get_data(as_text=True)
    footer = raw[raw.index('<footer'):]
    for code, subject_id in site["subjects"].items():
        assert f'href="/?subject={subject_id}">{code} ' in footer


def test_404_page_offers_search_and_browsing(client, site):
    response = client.get("/missing/page")
    raw = response.get_data(as_text=True)
    assert response.status_code == 404
    assert 'action="/"' in raw and 'name="q"' in raw
    assert 'href="/?semester=5">semester 5</a>' in raw


def test_favicons_and_share_image(client):
    ico = client.get("/favicon.ico")
    assert ico.status_code == 200 and ico.mimetype == "image/vnd.microsoft.icon"
    assert ico.data[:4] == b"\x00\x00\x01\x00"   # ICO header

    def png_size(path):
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", data[16:24])

    assert png_size(STATIC / "og-image.png") == (1200, 630)
    assert png_size(STATIC / "apple-touch-icon.png") == (180, 180)
    for name in ("favicon.svg", "og-image.png", "apple-touch-icon.png"):
        assert client.get(f"/static/{name}").status_code == 200


def test_no_source_maps_or_large_scripts():
    for path in STATIC.rglob("*"):
        assert not path.name.endswith(".map"), path
        if path.suffix in (".js", ".css"):
            assert "sourceMappingURL" not in path.read_text(encoding="utf-8"), path
    assert (STATIC / "js" / "main.js").stat().st_size < 4096
