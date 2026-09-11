"""
Event Media Hub — private photo and video galleries for events.

An organiser creates an event and shares its 6-character code (or invite link).
Guests who join can upload photos and videos, like and comment on them, and
download the whole gallery as a ZIP file.
"""
import mimetypes
import os
import re
import secrets
import sqlite3
import tempfile
import time
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash, safe_join

load_dotenv()

# Windows can map common extensions to the wrong MIME type via the registry, which
# stops scripts and videos loading once "X-Content-Type-Options: nosniff" is sent.
for _mime, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg"),
                    ("image/webp", ".webp"), ("video/mp4", ".mp4"), ("video/webm", ".webm"),
                    ("video/quicktime", ".mov"), ("application/manifest+json", ".webmanifest")):
    mimetypes.add_type(_mime, _ext)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SITE_NAME = "Event Media Hub"
SITE_DESCRIPTION = ("Create a private gallery for your event, share a 6-character code with your "
                    "guests, and collect everyone's photos and videos in one place.")
AUTHOR_NAME = "Takunda Nyangani"
AUTHOR_URL = "https://github.com/takundanyangani"
REPO_URL = "https://github.com/takundanyangani/event_media_hub"

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
ACCEPT_ATTRIBUTE = ",".join(f".{ext}" for ext in sorted(ALLOWED_EXTENSIONS))

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I look-alikes
CODE_LENGTH = 6
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MIN_PASSWORD_LENGTH = 8
MAX_EVENT_NAME_LENGTH = 100
MAX_COMMENT_LENGTH = 500

# Failed attempts allowed per IP address inside the window before we ask the visitor to wait.
LOGIN_ATTEMPTS, LOGIN_WINDOW = 10, 15 * 60
JOIN_ATTEMPTS, JOIN_WINDOW = 20, 15 * 60

# Pages that only make sense for signed-in users; kept out of search engines.
PRIVATE_PATHS = ("/dashboard", "/create_event", "/join_event", "/join/", "/event/", "/uploads/", "/logout")
SITEMAP_ENDPOINTS = ("index", "signup", "login")

CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "img-src 'self'",
    "media-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "script-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))


def env_flag(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


app = Flask(__name__)
DEBUG = env_flag("FLASK_DEBUG")

_secret_key = os.environ.get("SECRET_KEY", "").strip()
if not _secret_key:
    if not DEBUG:
        raise RuntimeError(
            "SECRET_KEY is not set. Copy .env.example to .env and set SECRET_KEY to a long random "
            'value, for example the output of: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    _secret_key = secrets.token_hex(32)
    app.logger.warning("SECRET_KEY is not set; using a temporary key, so everyone is logged out on restart.")

_site_url = os.environ.get("SITE_URL", "").strip().rstrip("/")

app.config.update(
    SECRET_KEY=_secret_key,
    DATABASE=os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "database.db"),
    UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER") or os.path.join(BASE_DIR, "uploads"),
    MAX_UPLOAD_MB=int(os.environ.get("MAX_UPLOAD_MB") or 100),
    SITE_URL=_site_url,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE", default=_site_url.startswith("https://")),
    WTF_CSRF_TIME_LIMIT=None,  # tokens last as long as the session, so long-open pages still submit
)
app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_UPLOAD_MB"] * 1024 * 1024

if env_flag("TRUST_PROXY"):
    # Behind a host such as Render, Railway or Nginx: trust X-Forwarded-* for HTTPS and client IPs.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

csrf = CSRFProtect(app)


# ─── Database ────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT UNIQUE,
    creator_id INTEGER
);
CREATE TABLE IF NOT EXISTS event_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    user_id INTEGER,
    UNIQUE(event_id, user_id)
);
-- "likes" is kept for databases created by older versions; counts now come from the likes table.
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    filename TEXT,
    likes INTEGER DEFAULT 0,
    original_name TEXT,
    uploader_id INTEGER,
    uploaded_at TEXT,
    FOREIGN KEY (event_id) REFERENCES events (id)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER,
    username TEXT,
    text TEXT,
    FOREIGN KEY (media_id) REFERENCES media (id)
);
CREATE TABLE IF NOT EXISTS likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER,
    username TEXT,
    UNIQUE(media_id, username)
);
CREATE INDEX IF NOT EXISTS idx_media_event ON media (event_id);
CREATE INDEX IF NOT EXISTS idx_comments_media ON comments (media_id);
CREATE INDEX IF NOT EXISTS idx_members_user ON event_members (user_id);
"""

# Columns added after the first release, so older databases can be upgraded in place.
MEDIA_COLUMNS_ADDED = {"original_name": "TEXT", "uploader_id": "INTEGER", "uploaded_at": "TEXT"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db = sqlite3.connect(app.config["DATABASE"])
    try:
        existing = {row[1] for row in db.execute("PRAGMA table_info(media)")}
        if existing:
            for column, column_type in MEDIA_COLUMNS_ADDED.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE media ADD COLUMN {column} {column_type}")
        db.executescript(SCHEMA)
        db.commit()
    finally:
        db.close()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── URLs, SEO helpers and template context ──────────────────────────────────

def site_origin():
    """The public origin (scheme + host). Set SITE_URL in production for a custom domain."""
    return app.config["SITE_URL"] or request.host_url.rstrip("/")


def absolute_url(path):
    return site_origin() + path


def canonical_url():
    return site_origin() + request.script_root + request.path


def breadcrumb_jsonld(crumbs):
    items = []
    for position, (name, path) in enumerate(crumbs, start=1):
        items.append({
            "@type": "ListItem",
            "position": position,
            "name": name,
            "item": absolute_url(path) if path else canonical_url(),
        })
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def home_structured_data():
    home = absolute_url(url_for("index"))
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{home}#website",
                "url": home,
                "name": SITE_NAME,
                "description": SITE_DESCRIPTION,
                "inLanguage": "en",
                "publisher": {"@id": f"{home}#author"},
            },
            {
                "@type": "WebApplication",
                "@id": f"{home}#app",
                "name": SITE_NAME,
                "url": home,
                "description": SITE_DESCRIPTION,
                "applicationCategory": "MultimediaApplication",
                "operatingSystem": "Any",
                "browserRequirements": "Requires a modern web browser",
                "image": absolute_url(url_for("static", filename="og-image.png")),
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "featureList": [
                    "Private, code-protected event galleries",
                    "Invite links for guests",
                    "Photo and video uploads",
                    "Likes and comments",
                    "Download the whole gallery as a ZIP file",
                ],
                "author": {"@id": f"{home}#author"},
            },
            {"@type": "Person", "@id": f"{home}#author", "name": AUTHOR_NAME, "url": AUTHOR_URL},
        ],
    }


app.add_template_global(breadcrumb_jsonld)


@app.context_processor
def inject_site_context():
    return {
        "site_name": SITE_NAME,
        "canonical_url": canonical_url(),
        "og_image_url": absolute_url(url_for("static", filename="og-image.png")),
        "author_name": AUTHOR_NAME,
        "author_url": AUTHOR_URL,
        "repo_url": REPO_URL,
        "current_year": datetime.now(timezone.utc).year,
        "logged_in": "user_id" in session,
        "max_upload_mb": app.config["MAX_UPLOAD_MB"],
    }


@app.after_request
def add_security_headers(response):
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if request.path.startswith(PRIVATE_PATHS):
        headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    if "user_id" in session and response.mimetype == "text/html":
        headers.setdefault("Cache-Control", "private, no-store")
    if app.config["SESSION_COOKIE_SECURE"]:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# ─── Auth helpers ────────────────────────────────────────────────────────────

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def safe_next_url(target):
    """Only allow redirects to a path on this site, which blocks open-redirect phishing links."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    return target


def start_session(user):
    session.clear()  # drop anything set before login (prevents session fixation)
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]


_failed_attempts = defaultdict(deque)


def _attempt_key(bucket):
    return bucket, request.remote_addr or "unknown"


def is_rate_limited(bucket, limit, window_seconds):
    attempts = _failed_attempts[_attempt_key(bucket)]
    cutoff = time.monotonic() - window_seconds
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= limit


def record_failed_attempt(bucket):
    _failed_attempts[_attempt_key(bucket)].append(time.monotonic())


# ─── Event and media helpers ─────────────────────────────────────────────────

def generate_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw):
    return re.sub(r"[\s-]", "", raw or "").upper()


def find_event_by_code(code):
    if len(code) != CODE_LENGTH:
        return None
    return get_db().execute("SELECT * FROM events WHERE code = ?", (code,)).fetchone()


def is_member(event_id, user_id):
    row = get_db().execute(
        "SELECT 1 FROM event_members WHERE event_id = ? AND user_id = ?", (event_id, user_id)
    ).fetchone()
    return row is not None


def load_event_for_member(event_id):
    """Return (event, is_creator) for the signed-in user, or stop with 404/403."""
    event = get_db().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        abort(404)
    user_id = session["user_id"]
    is_creator = event["creator_id"] == user_id
    if not is_creator and not is_member(event_id, user_id):
        abort(403)
    return event, is_creator


def get_media_or_404(media_id, event_id):
    media = get_db().execute(
        "SELECT * FROM media WHERE id = ? AND event_id = ?", (media_id, event_id)
    ).fetchone()
    if media is None:
        abort(404)
    return media


def allowed_extension(filename):
    if "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def display_name(filename):
    """The uploader's file name, stripped of any folder path. Only ever shown, never used on disk."""
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    return name[:200] or "upload"


def media_kind(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def upload_path(filename):
    """Absolute path of a stored upload, or None if the name would escape the upload folder."""
    return safe_join(app.config["UPLOAD_FOLDER"], filename)


def remove_upload(filename):
    path = upload_path(filename)
    if path and os.path.isfile(path):
        os.remove(path)


def unique_archive_name(name, used):
    base, ext = os.path.splitext(name)
    candidate, counter = name, 2
    while candidate.lower() in used:
        candidate = f"{base} ({counter}){ext}"
        counter += 1
    used.add(candidate.lower())
    return candidate


def slugify(text, fallback):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or fallback


def delete_media_rows(db, media_ids):
    for media_id in media_ids:
        db.execute("DELETE FROM comments WHERE media_id = ?", (media_id,))
        db.execute("DELETE FROM likes WHERE media_id = ?", (media_id,))
        db.execute("DELETE FROM media WHERE id = ?", (media_id,))


# ─── Public pages ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html", structured_data=home_structured_data())


@app.route("/signup", methods=["GET", "POST"])
def signup():
    next_url = safe_next_url(request.values.get("next"))
    if "user_id" in session:
        return redirect(next_url or url_for("dashboard"))

    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not USERNAME_PATTERN.match(username):
            error = "Usernames need 3–30 characters: letters, numbers, dots, dashes or underscores."
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
        else:
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "That username is taken. Please choose another one."
            else:
                start_session({"id": cursor.lastrowid, "username": username})
                flash(f"Welcome to {SITE_NAME}, {username}!", "success")
                return redirect(next_url or url_for("dashboard"))

    return render_template("signup.html", error=error, username=username, next_url=next_url,
                           min_password_length=MIN_PASSWORD_LENGTH)


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = safe_next_url(request.values.get("next"))
    if "user_id" in session:
        return redirect(next_url or url_for("dashboard"))

    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if is_rate_limited("login", LOGIN_ATTEMPTS, LOGIN_WINDOW):
            error = "Too many failed attempts. Please wait a few minutes and try again."
            return render_template("login.html", error=error, username=username, next_url=next_url), 429

        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password"], request.form.get("password", "")):
            start_session(user)
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(next_url or url_for("dashboard"))

        record_failed_attempt("login")
        error = "Invalid username or password. Please try again."

    return render_template("login.html", error=error, username=username, next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ─── Signed-in pages ─────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    db = get_db()
    created_events = db.execute("""
        SELECT events.*, (SELECT COUNT(*) FROM media WHERE media.event_id = events.id) AS media_count
        FROM events WHERE creator_id = ? ORDER BY events.id DESC
    """, (user_id,)).fetchall()
    joined_events = db.execute("""
        SELECT events.*, (SELECT COUNT(*) FROM media WHERE media.event_id = events.id) AS media_count
        FROM events JOIN event_members ON events.id = event_members.event_id
        WHERE event_members.user_id = ? AND events.creator_id != ?
        ORDER BY events.id DESC
    """, (user_id, user_id)).fetchall()
    return render_template("dashboard.html", created_events=created_events, joined_events=joined_events)


@app.route("/create_event", methods=["GET", "POST"])
@login_required
def create_event():
    error = None
    event_name = ""
    if request.method == "POST":
        event_name = " ".join(request.form.get("event_name", "").split())
        if not event_name:
            error = "Please give your event a name."
        elif len(event_name) > MAX_EVENT_NAME_LENGTH:
            error = f"Event names can be up to {MAX_EVENT_NAME_LENGTH} characters."
        else:
            db = get_db()
            for _ in range(10):  # a clash is very unlikely; retry with a fresh code if it happens
                try:
                    cursor = db.execute(
                        "INSERT INTO events (name, code, creator_id) VALUES (?, ?, ?)",
                        (event_name, generate_code(), session["user_id"]),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    continue
                flash("Event created! Share the code or invite link below with your guests.", "success")
                return redirect(url_for("event_page", event_id=cursor.lastrowid))
            error = "We couldn't create a unique event code. Please try again."

    return render_template("create_event.html", error=error, event_name=event_name,
                           max_length=MAX_EVENT_NAME_LENGTH)


def _join(event):
    user_id = session["user_id"]
    if event["creator_id"] != user_id:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO event_members (event_id, user_id) VALUES (?, ?)",
                   (event["id"], user_id))
        db.commit()
        flash(f"You joined “{event['name']}”.", "success")
    return redirect(url_for("event_page", event_id=event["id"]))


@app.route("/join_event", methods=["GET", "POST"])
@login_required
def join_event():
    if request.method == "GET":
        return render_template("join_event.html", code="", invited_event=None)

    if is_rate_limited("join", JOIN_ATTEMPTS, JOIN_WINDOW):
        error = "Too many incorrect codes. Please wait a few minutes and try again."
        return render_template("join_event.html", code="", invited_event=None, error=error), 429

    code = normalize_code(request.form.get("code", ""))
    event = find_event_by_code(code)
    if event is None:
        record_failed_attempt("join")
        error = "That code doesn't match any event. Check it and try again."
        return render_template("join_event.html", code=code, invited_event=None, error=error)
    return _join(event)


@app.route("/join/<code>")
@login_required
def join_via_link(code):
    """Invite links show the event name and ask for confirmation before joining."""
    if is_rate_limited("join", JOIN_ATTEMPTS, JOIN_WINDOW):
        error = "Too many incorrect codes. Please wait a few minutes and try again."
        return render_template("join_event.html", code="", invited_event=None, error=error), 429

    code = normalize_code(code)
    event = find_event_by_code(code)
    if event is None:
        record_failed_attempt("join")
        error = "This invite link isn't valid. Ask the organiser for the event code."
        return render_template("join_event.html", code="", invited_event=None, error=error), 404
    if event["creator_id"] == session["user_id"] or is_member(event["id"], session["user_id"]):
        return redirect(url_for("event_page", event_id=event["id"]))
    return render_template("join_event.html", code=code, invited_event=event)


@app.route("/event/<int:event_id>")
@login_required
def event_page(event_id):
    event, is_creator = load_event_for_member(event_id)
    db = get_db()
    rows = db.execute("""
        SELECT media.id, media.filename, media.original_name, media.uploader_id,
               users.username AS uploader_name,
               (SELECT COUNT(*) FROM likes WHERE likes.media_id = media.id) AS like_count,
               EXISTS (SELECT 1 FROM likes WHERE likes.media_id = media.id AND likes.username = ?) AS liked
        FROM media LEFT JOIN users ON users.id = media.uploader_id
        WHERE media.event_id = ?
        ORDER BY media.id DESC
    """, (session.get("username"), event_id)).fetchall()

    comments = defaultdict(list)
    for comment in db.execute("""
        SELECT comments.media_id, comments.username, comments.text
        FROM comments JOIN media ON media.id = comments.media_id
        WHERE media.event_id = ? ORDER BY comments.id
    """, (event_id,)):
        comments[comment["media_id"]].append(comment)

    user_id = session["user_id"]
    media = [{
        "id": row["id"],
        "filename": row["filename"],
        "kind": media_kind(row["filename"]),
        "uploader": row["uploader_name"],
        "like_count": row["like_count"],
        "liked": bool(row["liked"]),
        "can_delete": is_creator or row["uploader_id"] == user_id,
        "comments": comments.get(row["id"], []),
    } for row in rows]

    return render_template(
        "event.html",
        event=event,
        media=media,
        is_creator=is_creator,
        invite_url=absolute_url(url_for("join_via_link", code=event["code"])),
        accept=ACCEPT_ATTRIBUTE,
        max_comment_length=MAX_COMMENT_LENGTH,
    )


@app.route("/event/<int:event_id>/upload", methods=["POST"])
@login_required
def upload_media(event_id):
    load_event_for_member(event_id)
    files = [f for f in request.files.getlist("media") if f and f.filename]
    if not files:
        flash("Choose at least one photo or video to upload.", "error")
        return redirect(url_for("event_page", event_id=event_id))

    db = get_db()
    saved, skipped = 0, []
    for file in files:
        ext = allowed_extension(file.filename)
        if ext is None:
            skipped.append(display_name(file.filename))
            continue
        stored_name = f"{uuid.uuid4().hex}.{ext}"  # never trust the uploader's file name on disk
        file.save(upload_path(stored_name))
        db.execute(
            "INSERT INTO media (event_id, filename, original_name, uploader_id, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, stored_name, display_name(file.filename), session["user_id"], utc_now()),
        )
        saved += 1
    db.commit()

    if saved:
        flash(f"Uploaded {saved} file{'s' if saved != 1 else ''}.", "success")
    if skipped:
        names = ", ".join(skipped[:3]) + ("…" if len(skipped) > 3 else "")
        flash(f"Skipped {names}: only JPG, PNG, GIF, WebP, MP4, WebM and MOV files are allowed.", "error")
    return redirect(url_for("event_page", event_id=event_id))


@app.route("/event/<int:event_id>/media/<int:media_id>/like", methods=["POST"])
@login_required
def toggle_like(event_id, media_id):
    load_event_for_member(event_id)
    get_media_or_404(media_id, event_id)
    db = get_db()
    username = session["username"]
    removed = db.execute("DELETE FROM likes WHERE media_id = ? AND username = ?", (media_id, username)).rowcount
    if not removed:
        db.execute("INSERT INTO likes (media_id, username) VALUES (?, ?)", (media_id, username))
    db.commit()
    return redirect(url_for("event_page", event_id=event_id, _anchor=f"media-{media_id}"))


@app.route("/event/<int:event_id>/media/<int:media_id>/comment", methods=["POST"])
@login_required
def add_comment(event_id, media_id):
    load_event_for_member(event_id)
    get_media_or_404(media_id, event_id)
    text = " ".join(request.form.get("comment", "").split())
    if not text:
        flash("Comments can't be empty.", "error")
    elif len(text) > MAX_COMMENT_LENGTH:
        flash(f"Comments can be up to {MAX_COMMENT_LENGTH} characters.", "error")
    else:
        db = get_db()
        db.execute("INSERT INTO comments (media_id, username, text) VALUES (?, ?, ?)",
                   (media_id, session["username"], text))
        db.commit()
    return redirect(url_for("event_page", event_id=event_id, _anchor=f"media-{media_id}"))


@app.route("/event/<int:event_id>/media/<int:media_id>/delete", methods=["POST"])
@login_required
def delete_media(event_id, media_id):
    _, is_creator = load_event_for_member(event_id)
    media = get_media_or_404(media_id, event_id)
    if not is_creator and media["uploader_id"] != session["user_id"]:
        abort(403)
    db = get_db()
    delete_media_rows(db, [media_id])
    db.commit()
    remove_upload(media["filename"])
    flash("File deleted.", "info")
    return redirect(url_for("event_page", event_id=event_id))


@app.route("/event/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event(event_id):
    event, is_creator = load_event_for_member(event_id)
    if not is_creator:
        abort(403)
    db = get_db()
    media = db.execute("SELECT id, filename FROM media WHERE event_id = ?", (event_id,)).fetchall()
    delete_media_rows(db, [row["id"] for row in media])
    db.execute("DELETE FROM event_members WHERE event_id = ?", (event_id,))
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    for row in media:
        remove_upload(row["filename"])
    flash(f"Deleted “{event['name']}” and all of its media.", "info")
    return redirect(url_for("dashboard"))


@app.route("/event/<int:event_id>/download")
@login_required
def download_event(event_id):
    event, _ = load_event_for_member(event_id)
    rows = get_db().execute(
        "SELECT filename, original_name FROM media WHERE event_id = ? ORDER BY id", (event_id,)
    ).fetchall()
    if not rows:
        flash("There's nothing to download yet.", "info")
        return redirect(url_for("event_page", event_id=event_id))

    # Built in a temporary file (not in static/) so archives are never publicly reachable.
    archive = tempfile.TemporaryFile()
    used_names = set()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:  # photos/videos are already compressed
        for row in rows:
            path = upload_path(row["filename"])
            if path and os.path.isfile(path):
                zf.write(path, unique_archive_name(display_name(row["original_name"] or row["filename"]), used_names))
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", as_attachment=True,
                     download_name=f"{slugify(event['name'], f'event-{event_id}')}-media.zip")


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    media = get_db().execute("SELECT event_id FROM media WHERE filename = ?", (filename,)).fetchone()
    if media is None:
        abort(404)
    load_event_for_member(media["event_id"])
    if allowed_extension(filename) is None:
        # Files uploaded by older versions could be any type (e.g. .html); never let the browser run them.
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True,
                                   mimetype="application/octet-stream")
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ─── Search engines, AI crawlers and icons ───────────────────────────────────

@app.route("/robots.txt")
def robots_txt():
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {path}" for path in PRIVATE_PATHS]
    lines += ["", f"Sitemap: {absolute_url(url_for('sitemap_xml'))}", ""]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = "".join(
        f"  <url><loc>{xml_escape(absolute_url(url_for(endpoint)))}</loc></url>\n"
        for endpoint in SITEMAP_ENDPOINTS
    )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{urls}</urlset>\n")
    return Response(xml, mimetype="application/xml")


@app.route("/llms.txt")
def llms_txt():
    return Response(render_template("llms.txt", home_url=absolute_url(url_for("index")),
                                    signup_url=absolute_url(url_for("signup")),
                                    login_url=absolute_url(url_for("login"))),
                    mimetype="text/plain")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")


# ─── Error pages ─────────────────────────────────────────────────────────────

ERROR_PAGES = {
    400: ("Bad request", "That request didn't work", "Please go back, refresh the page and try again."),
    403: ("Access denied", "You don't have access to this page",
          "Only members of an event can see its photos and videos, and only organisers can delete events. "
          "Ask the organiser for the event code or invite link."),
    404: ("Page not found", "We couldn't find that page",
          "The link may be broken, or the event or file may have been deleted."),
    405: ("Method not allowed", "That action isn't available here", "Please use the buttons on the page instead."),
    413: ("Upload too large", "That upload is too large", None),
    429: ("Too many requests", "Please slow down", "Wait a few minutes, then try again."),
    500: ("Server error", "Something went wrong on our side", "Please try again in a moment."),
}


def render_error(code, message=None):
    title, heading, default_message = ERROR_PAGES[code]
    if code == 413:
        default_message = (f"You can upload up to {app.config['MAX_UPLOAD_MB']} MB at a time. "
                           "Try sending fewer or smaller files.")
    return render_template("errors/error.html", code=code, title=title, heading=heading,
                           message=message or default_message), code


@app.errorhandler(CSRFError)
def handle_csrf_error(_error):
    return render_error(400, "Your form expired or came from another site. Go back, refresh the page and try again.")


for _code in ERROR_PAGES:
    app.register_error_handler(_code, lambda error, code=_code: render_error(code))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=DEBUG)
