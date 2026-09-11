# 📸 Event Media Hub

> Private photo and video galleries for events. Create a gallery, share a 6-character code or invite link with your guests, and collect everyone's memories in one place.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.1-black?style=flat-square&logo=flask)
![SQLite](https://img.shields.io/badge/SQLite-3-lightblue?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
[![tests](https://github.com/takundanyangani/event_media_hub/actions/workflows/tests.yml/badge.svg)](https://github.com/takundanyangani/event_media_hub/actions/workflows/tests.yml)

---

## 🌟 What it does

Event Media Hub lets you create private galleries for birthdays, weddings, school trips and team outings. Guests join with a 6-character code or an invite link, then upload their own photos and videos, like and comment on them, and download the whole gallery as a ZIP file. Only members of an event can see its media.

## ✨ Features

| Feature | Description |
|---|---|
| 🔐 **User accounts** | Sign up and log in; passwords are hashed with Werkzeug |
| 🎉 **Events** | Create named events with unique, easy-to-read 6-character codes |
| 🔗 **Invite links** | Share `/join/<code>`; guests see the event name and confirm before joining |
| 📤 **Uploads** | Several photos (JPG, PNG, GIF, WebP) or videos (MP4, WebM, MOV) at once, with drag and drop |
| ❤️ **Likes** | One like per person per file; click again to unlike |
| 💬 **Comments** | Comment on any photo or video in the event |
| ⬇️ **Bulk download** | Download every file in an event as one ZIP, using the original file names |
| 🗑️ **Delete controls** | Guests can remove their own uploads; organisers can remove anything or delete the event |
| 🌙 **Dark, responsive UI** | Works on phones, tablets and computers; keyboard and screen-reader friendly |

## 🛡️ Security

- **Private media** — every page, upload and download checks that you created or joined the event.
- **Safe uploads** — only photo and video types are accepted, files are saved under random names (so nobody can overwrite another file or escape the uploads folder), and the upload size is capped.
- **CSRF protection** on every form (Flask-WTF), and every action that changes data uses `POST`.
- **Login and join-code rate limiting**, session cookies that are `HttpOnly` and `SameSite=Lax`, and sessions reset at login.
- **Security headers** — a strict Content-Security-Policy with no inline scripts, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and HSTS when served over HTTPS.
- **No secrets in code** — the secret key comes from the environment, and the app refuses to start in production without one.

## 🚀 Getting started

**Requirements:** Python 3.10 or newer.

```bash
# 1. Clone the repository
git clone https://github.com/takundanyangani/event_media_hub.git
cd event_media_hub

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env           # Windows: copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste the output as SECRET_KEY in .env
# For local development you can also set FLASK_DEBUG=1 in .env

# 5. Run
python app.py
```

Open **http://127.0.0.1:5000**. The database (`database.db`) and `uploads/` folder are created automatically.

## ⚙️ Configuration

All settings are environment variables (or lines in `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | — | **Required.** Long random string that signs login cookies |
| `SITE_URL` | *(browser address)* | Public origin, e.g. `https://events.example.com`; used for canonical links, the sitemap, invite links and share previews |
| `FLASK_DEBUG` | `0` | `1` for local development only |
| `MAX_UPLOAD_MB` | `100` | Largest upload request, in MB |
| `TRUST_PROXY` | `0` | `1` when behind a proxy/load balancer (Render, Railway, Nginx) |
| `SESSION_COOKIE_SECURE` | on if `SITE_URL` is `https://` | Send cookies over HTTPS only |
| `DATABASE_PATH` / `UPLOAD_FOLDER` | next to `app.py` | Where data is stored (point these at a persistent disk in production) |

## 🌐 Deploying with a custom domain

1. Deploy the app to a host that runs Python (for example Render, Railway or PythonAnywhere). Start it with a production server such as `gunicorn app:app` on Linux or `waitress-serve app:app` on Windows. Install that server separately; it isn't in `requirements.txt`.
2. Set `SECRET_KEY`, `SITE_URL=https://your-domain`, `TRUST_PROXY=1`, and persistent `DATABASE_PATH`/`UPLOAD_FOLDER` locations.
3. In your domain's DNS settings, add the `CNAME` (or `A`) record your host gives you, and turn on HTTPS in the host's dashboard.
4. Submit `https://your-domain/sitemap.xml` in Google Search Console.

## 🔎 Search, sharing and AI crawlers

- Unique `<title>`, meta description and single `<h1>` on every page, with canonical links built from `SITE_URL`
- `robots.txt`, `sitemap.xml` (public pages only) and `llms.txt`
- Open Graph and Twitter card tags with a 1200×630 share image
- JSON-LD structured data: `WebSite`, `WebApplication` and `Person` on the home page, and `BreadcrumbList` on every page with breadcrumbs
- Private pages send `noindex`, so event galleries never appear in search results
- Favicon (`.ico` and `.svg`), Apple touch icon and web app manifest
- Custom 403, 404, 413 and 500 error pages

## 🧪 Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers access control, upload safety, CSRF, rate limiting, redirects and the SEO endpoints. It also runs on every push through GitHub Actions.

## 📁 Project structure

```
event_media_hub/
├── app.py                 # Flask app: routes, security, database
├── requirements.txt       # Runtime dependencies (pinned)
├── requirements-dev.txt   # Test dependencies
├── .env.example           # Settings template (copy to .env)
├── templates/             # Jinja2 pages, incl. errors/ and llms.txt
├── static/                # CSS, JS, icons, share image, web manifest
├── tests/                 # pytest suite
└── .github/workflows/     # CI
```

## 🗄️ Database schema

```
users           → id, username, password (hashed)
events          → id, name, code, creator_id
event_members   → id, event_id, user_id
media           → id, event_id, filename (random), original_name, uploader_id, uploaded_at
comments        → id, media_id, username, text
likes           → id, media_id, username (unique per user)
```

Databases created by earlier versions are upgraded automatically the first time the app starts.

## 🛣️ Roadmap

- [ ] Analytics (uploads per day, most-liked media)
- [ ] Profile pictures
- [ ] Event expiry / auto-delete
- [ ] Image compression and thumbnails on upload
- [ ] QR code for the invite link

## 📄 License

[MIT](LICENSE) © Takunda Nyangani

## 👨‍💻 Author

Built by **[Takunda Nyangani](https://github.com/takundanyangani)**. Feel free to open an issue or star the repo if you find it useful.
