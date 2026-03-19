# 📸 Event Media Hub

> A private, code-protected photo and video sharing platform built for events. Create a gallery, share the access code with guests, and collect everyone's memories in one place.

![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
![SQLite](https://img.shields.io/badge/SQLite-3-lightblue?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## 🌟 What It Does

Event Media Hub lets you create private galleries for events — birthdays, weddings, school trips, team outings — and invite guests to upload their own photos and videos using a 6-character access code. No one can enter the gallery without the code, keeping your event media private and organised.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔐 **User Accounts** | Secure signup and login with hashed passwords |
| 🎉 **Event Creation** | Create named events with auto-generated 6-char codes |
| 🔗 **Code-based Joining** | Share the code — guests join instantly |
| 📤 **Media Upload** | Upload photos (JPG, PNG, GIF) and videos (MP4, WebM) |
| ❤️ **Likes** | One like per user per photo — no duplicates |
| 💬 **Comments** | Comment on any photo or video |
| ⬇️ **Bulk Download** | Download all event media as a ZIP file |
| 🗑️ **Delete Controls** | Event creators can delete media or entire events |
| 🌙 **Dark UI** | Clean, modern dark-themed interface |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- pip

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/event-media-hub.git
cd event-media-hub

# 2. Create a virtual environment (recommended)
python -m venv venv

# Activate it:
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python app.py
```

Then open your browser and go to: **http://127.0.0.1:5000**

The database (`database.db`) and upload folders are created automatically on first run.

---

## 📁 Project Structure

```
event-media-hub/
│
├── app.py                  # Main Flask application & all routes
├── database.db             # SQLite database (auto-created)
├── requirements.txt        # Python dependencies
│
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Shared layout (navbar, fonts, CSS)
│   ├── login.html          # Login page
│   ├── signup.html         # Signup page
│   ├── dashboard.html      # User dashboard
│   ├── create_event.html   # Create new event
│   ├── join_event.html     # Join event by code
│   └── event.html          # Event gallery page
│
├── static/
│   └── style.css           # Global stylesheet
│
└── uploads/                # Uploaded media files (auto-created)
```

---

## 🔑 How to Use

1. **Sign up** for an account at `/signup`
2. **Create an event** — you'll get a 6-character code (e.g. `AB3X9Z`)
3. **Share the code** with your guests
4. Guests **sign up and join** using the code at `/join_event`
5. Everyone can **upload, like, and comment** on media
6. The event creator can **download all media as a ZIP** or delete files

---

## 🗄️ Database Schema

```
users           → id, username, password (hashed)
events          → id, name, code, creator_id
event_members   → id, event_id, user_id
media           → id, event_id, filename, likes
comments        → id, media_id, username, text
likes           → id, media_id, username (unique per user)
```

---

## ⚙️ Configuration

In `app.py`, change these before deploying:

```python
app.secret_key = "your_secret_key"  # ← Change to a long random string
```

Generate a secure key:
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🛣️ Roadmap

- [ ] Analytics dashboard (uploads per day, most liked media)
- [ ] Profile pictures
- [ ] Event expiry / auto-delete
- [ ] Image compression on upload
- [ ] Mobile-optimised upload (camera capture)

---

## 🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## 📄 License

This project is licensed under the MIT License.

---

## 👨‍💻 Author

Built by **[Your Name]** — feel free to reach out or star the repo if you found it useful!
