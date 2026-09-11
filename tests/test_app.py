import html
import io
import json
import os
import re
import sqlite3
import zipfile
from contextlib import closing

import app as app_module

PASSWORD = "correct-horse-battery"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def signup(client, username="alice", password=PASSWORD, **extra):
    return client.post("/signup", data={"username": username, "password": password, **extra})


def login(client, username="alice", password=PASSWORD, **extra):
    return client.post("/login", data={"username": username, "password": password, **extra})


def create_event(client, name="Tariro 21st Birthday"):
    response = client.post("/create_event", data={"event_name": name})
    assert response.status_code == 302
    return int(response.headers["Location"].rstrip("/").rsplit("/", 1)[1])


def query(app, sql, params=()):
    with closing(sqlite3.connect(app.config["DATABASE"])) as db:
        return db.execute(sql, params).fetchall()


def event_code(app, event_id):
    return query(app, "SELECT code FROM events WHERE id = ?", (event_id,))[0][0]


def upload(client, event_id, *files):
    data = {"media": [(io.BytesIO(content), name) for name, content in files]}
    return client.post(f"/event/{event_id}/upload", data=data, content_type="multipart/form-data")


def stored_media(app, event_id):
    return query(app, "SELECT id, filename, original_name FROM media WHERE event_id = ? ORDER BY id", (event_id,))


def json_ld_blocks(html):
    return [json.loads(block) for block in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


# ─── SEO and public pages ────────────────────────────────────────────────────

def test_public_pages_have_unique_titles_descriptions_and_one_h1(client):
    titles = set()
    for path in ("/", "/login", "/signup"):
        response = client.get(path)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert f'<link rel="canonical" href="http://localhost{path}">' in html
        assert '<meta name="description" content="' in html
        assert '<meta property="og:image" content="http://localhost/static/og-image.png">' in html
        assert '<meta name="twitter:card" content="summary_large_image">' in html
        assert html.count("<h1") == 1
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        assert "Vite" not in title and "React" not in title
        titles.add(title)
    assert len(titles) == 3


def test_home_page_structured_data(client):
    blocks = json_ld_blocks(client.get("/").get_data(as_text=True))
    types = {node["@type"] for block in blocks for node in block.get("@graph", [block])}
    assert {"WebSite", "WebApplication", "Person"} <= types


def test_breadcrumbs_are_visible_and_structured(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'aria-label="Breadcrumb"' in html
    crumbs = [b for b in json_ld_blocks(html) if b.get("@type") == "BreadcrumbList"]
    assert [item["name"] for item in crumbs[0]["itemListElement"]] == ["Home", "Log in"]
    assert crumbs[0]["itemListElement"][0]["item"] == "http://localhost/"


def test_site_url_setting_is_used_for_canonical_and_sitemap(app, client):
    app.config["SITE_URL"] = "https://events.example.com"
    html = client.get("/signup").get_data(as_text=True)
    assert '<link rel="canonical" href="https://events.example.com/signup">' in html
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    assert "<loc>https://events.example.com/</loc>" in sitemap
    assert "Sitemap: https://events.example.com/sitemap.xml" in client.get("/robots.txt").get_data(as_text=True)


def test_robots_sitemap_llms_and_icons(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and robots.mimetype == "text/plain"
    assert "Disallow: /uploads/" in robots.get_data(as_text=True)

    sitemap = client.get("/sitemap.xml")
    assert sitemap.mimetype == "application/xml"
    assert sitemap.get_data(as_text=True).count("<url>") == 3

    llms = client.get("/llms.txt")
    assert llms.status_code == 200
    assert llms.get_data(as_text=True).startswith("# Event Media Hub")

    for path in ("/favicon.ico", "/static/favicon.svg", "/static/apple-touch-icon.png",
                 "/static/og-image.png", "/static/site.webmanifest", "/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200, path
    assert client.get("/static/app.js").mimetype == "text/javascript"


def test_custom_404_page(client):
    response = client.get("/no-such-page")
    html = response.get_data(as_text=True)
    assert response.status_code == 404
    assert "Page not found" in html
    assert 'content="noindex, nofollow"' in html
    assert 'rel="canonical"' not in html


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_pages_have_no_inline_scripts_or_styles(client):
    signup(client)
    event_id = create_event(client)
    for path in ("/", "/dashboard", "/create_event", "/join_event", f"/event/{event_id}"):
        html = client.get(path).get_data(as_text=True)
        assert " style=" not in html, path
        assert " onclick=" not in html and " onchange=" not in html, path
        scripts = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
        assert all('type="application/ld+json"' in attrs for attrs in scripts), path


# ─── Accounts ────────────────────────────────────────────────────────────────

def test_signup_validation(client):
    assert "at least 8 characters" in signup(client, password="short").get_data(as_text=True)
    assert "3–30 characters" in signup(client, username="a b").get_data(as_text=True)
    assert signup(client).status_code == 302
    client.post("/logout")
    assert "That username is taken" in signup(client).get_data(as_text=True)


def test_signup_logs_in_and_follows_safe_next(client):
    response = signup(client, next="/join_event")
    assert response.headers["Location"] == "/join_event"
    assert client.get("/dashboard").status_code == 200


def test_login_blocks_open_redirects(client):
    signup(client)
    client.post("/logout")
    for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
        assert login(client, next=target).headers["Location"] == "/dashboard"
        client.post("/logout")
    assert login(client, next="/join_event").headers["Location"] == "/join_event"


def test_login_is_rate_limited(client):
    signup(client)
    client.post("/logout")
    for _ in range(app_module.LOGIN_ATTEMPTS):
        assert login(client, password="wrong-password").status_code == 200
    assert login(client).status_code == 429


def test_logout_requires_post(client):
    signup(client)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_private_pages_require_login(client):
    for path in ("/dashboard", "/create_event", "/join_event", "/event/1", "/event/1/download"):
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login?next=")


def test_csrf_tokens_are_required_and_present(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        rejected = client.post("/signup", data={"username": "alice", "password": PASSWORD})
        assert rejected.status_code == 400
        assert "Your form expired" in rejected.get_data(as_text=True)

        page = client.get("/signup").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        accepted = client.post("/signup", data={"username": "alice", "password": PASSWORD, "csrf_token": token})
        assert accepted.status_code == 302
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# ─── Events, membership and access control ──────────────────────────────────

def test_join_with_lowercase_code(app, client, other_client):
    signup(client)
    event_id = create_event(client)
    signup(other_client, "bob")
    response = other_client.post("/join_event", data={"code": event_code(app, event_id).lower()})
    assert response.headers["Location"] == f"/event/{event_id}"
    assert other_client.get(f"/event/{event_id}").status_code == 200


def test_invite_link_asks_before_joining(app, client, other_client):
    signup(client)
    event_id = create_event(client, "Graduation Party")
    code = event_code(app, event_id)
    signup(other_client, "bob")
    page = other_client.get(f"/join/{code}")
    assert page.status_code == 200 and "Graduation Party" in page.get_data(as_text=True)
    assert other_client.get(f"/event/{event_id}").status_code == 403  # not joined yet
    other_client.post("/join_event", data={"code": code})
    assert other_client.get(f"/join/{code}").headers["Location"] == f"/event/{event_id}"


def test_invalid_codes(client):
    signup(client)
    page = html.unescape(client.post("/join_event", data={"code": "ZZZZZZ"}).get_data(as_text=True))
    assert "doesn't match any event" in page
    assert client.get("/join/ZZZZZZ").status_code == 404


def test_non_members_cannot_see_media_or_download(app, client, other_client):
    signup(client)
    event_id = create_event(client)
    upload(client, event_id, ("photo.jpg", b"jpeg-bytes"))
    stored = stored_media(app, event_id)[0][1]

    signup(other_client, "mallory")
    assert other_client.get(f"/event/{event_id}").status_code == 403
    assert other_client.get(f"/uploads/{stored}").status_code == 403
    assert other_client.get(f"/event/{event_id}/download").status_code == 403

    anonymous = app.test_client()
    assert anonymous.get(f"/uploads/{stored}").status_code == 302
    assert anonymous.get(f"/event/{event_id}/download").status_code == 302


def test_only_the_organiser_can_delete_an_event(app, client, other_client):
    signup(client)
    event_id = create_event(client)
    upload(client, event_id, ("photo.jpg", b"jpeg-bytes"))
    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_media(app, event_id)[0][1])

    signup(other_client, "bob")
    other_client.post("/join_event", data={"code": event_code(app, event_id)})
    assert other_client.post(f"/event/{event_id}/delete").status_code == 403
    assert client.get(f"/event/{event_id}/delete").status_code == 405

    assert client.post(f"/event/{event_id}/delete").status_code == 302
    assert query(app, "SELECT COUNT(*) FROM events")[0][0] == 0
    assert not os.path.exists(stored_path)


def test_uploaders_can_delete_their_own_media_only(app, client, other_client):
    signup(client)
    event_id = create_event(client)
    signup(other_client, "bob")
    other_client.post("/join_event", data={"code": event_code(app, event_id)})

    upload(client, event_id, ("alice.jpg", b"a"))
    upload(other_client, event_id, ("bob.jpg", b"b"))
    (alice_media, _, _), (bob_media, _, _) = stored_media(app, event_id)

    assert other_client.post(f"/event/{event_id}/media/{alice_media}/delete").status_code == 403
    assert other_client.post(f"/event/{event_id}/media/{bob_media}/delete").status_code == 302
    assert client.post(f"/event/{event_id}/media/{alice_media}/delete").status_code == 302
    assert stored_media(app, event_id) == []


# ─── Uploads, likes, comments and downloads ─────────────────────────────────

def test_uploads_get_random_names_and_unsafe_types_are_rejected(app, client):
    signup(client)
    event_id = create_event(client)
    response = upload(client, event_id, ("../../evil.jpg", b"jpeg-bytes"), ("page.html", b"<script>alert(1)</script>"))
    assert response.status_code == 302

    rows = stored_media(app, event_id)
    assert len(rows) == 1
    _, stored_name, original_name = rows[0]
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", stored_name)
    assert original_name == "evil.jpg"
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == [stored_name]

    html = client.get(f"/event/{event_id}").get_data(as_text=True)
    assert "Skipped page.html" in html
    assert 'alt="Photo from Tariro 21st Birthday, shared by alice"' in html


def test_upload_that_is_too_large_gets_a_friendly_page(app, client):
    signup(client)
    event_id = create_event(client)
    app.config["MAX_CONTENT_LENGTH"] = 1024
    response = upload(client, event_id, ("big.jpg", b"x" * 4096))
    assert response.status_code == 413
    assert "That upload is too large" in response.get_data(as_text=True)


def test_like_toggles_and_comments_stay_in_their_event(app, client):
    signup(client)
    first = create_event(client, "First Event")
    second = create_event(client, "Second Event")
    upload(client, first, ("one.jpg", b"1"))
    upload(client, second, ("two.jpg", b"2"))
    media_id = stored_media(app, first)[0][0]

    client.post(f"/event/{first}/media/{media_id}/like")
    assert query(app, "SELECT COUNT(*) FROM likes")[0][0] == 1
    client.post(f"/event/{first}/media/{media_id}/like")
    assert query(app, "SELECT COUNT(*) FROM likes")[0][0] == 0

    client.post(f"/event/{first}/media/{media_id}/comment", data={"comment": "Great shot!"})
    assert "Great shot!" in client.get(f"/event/{first}").get_data(as_text=True)
    assert "Great shot!" not in client.get(f"/event/{second}").get_data(as_text=True)

    # media from another event can't be targeted through this event's URL
    other_media = stored_media(app, second)[0][0]
    assert client.post(f"/event/{first}/media/{other_media}/like").status_code == 404


def test_download_contains_original_names_without_clashes(app, client):
    signup(client)
    event_id = create_event(client, "Beach Day!")
    upload(client, event_id, ("photo.jpg", b"first"), ("photo.jpg", b"second"), ("clip.mp4", b"video"))
    response = client.get(f"/event/{event_id}/download")
    assert response.status_code == 200
    assert "beach-day-media.zip" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert sorted(archive.namelist()) == ["clip.mp4", "photo (2).jpg", "photo.jpg"]
    response.close()


def test_legacy_database_is_upgraded(app, tmp_path):
    legacy = tmp_path / "legacy.db"
    with closing(sqlite3.connect(legacy)) as db:
        db.execute("CREATE TABLE media (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, "
                   "filename TEXT, likes INTEGER DEFAULT 0)")
        db.commit()
    app.config["DATABASE"] = str(legacy)
    app_module.init_db()
    with closing(sqlite3.connect(legacy)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(media)")}
    assert {"original_name", "uploader_id", "uploaded_at"} <= columns
