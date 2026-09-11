import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# app.py reads its settings when imported, so point it at throwaway locations first.
_IMPORT_DIR = tempfile.mkdtemp(prefix="event-media-hub-tests-")
os.environ["SECRET_KEY"] = "test-only-secret-key"
os.environ["DATABASE_PATH"] = os.path.join(_IMPORT_DIR, "import.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(_IMPORT_DIR, "uploads")
os.environ["SITE_URL"] = ""

import app as app_module  # noqa: E402


@pytest.fixture
def app(tmp_path):
    flask_app = app_module.app
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        DATABASE=str(tmp_path / "test.db"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        SITE_URL="",
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    app_module._failed_attempts.clear()
    app_module.init_db()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def other_client(app):
    return app.test_client()
