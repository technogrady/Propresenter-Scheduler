"""Church announcement portal.

Volunteers upload a photo with a start/end date. Every image is normalized to a
1920x1080 letterboxed JPEG and stored permanently in ~/Announcements/library/.
A sync step keeps ~/Announcements/active/ containing exactly the announcements
whose date range includes today — ProPresenter watches that folder as a Smart
Playlist. This app never talks to ProPresenter directly.
"""

import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import (Flask, flash, redirect, render_template, request,
                   send_from_directory, session, url_for)
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()  # lets Pillow open .heic files from iPhones

# ---------------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = Path.home() / "Announcements"
LIBRARY_DIR = BASE_DIR / "library"   # permanent storage of processed images
ACTIVE_DIR = BASE_DIR / "active"     # folder ProPresenter watches
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = BASE_DIR / "data.db"

CANVAS_SIZE = (1920, 1080)
SYNC_INTERVAL_SECONDS = 15 * 60
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def load_dotenv(path):
    """Tiny .env parser (KEY=VALUE lines) so we don't need python-dotenv."""
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip("'\"")
    return env


_env = load_dotenv(APP_DIR / ".env")
PORTAL_PASSWORD = _env.get("PORTAL_PASSWORD") or os.environ.get("PORTAL_PASSWORD")
SECRET_KEY = _env.get("SECRET_KEY") or os.environ.get("SECRET_KEY")

if not PORTAL_PASSWORD or not SECRET_KEY:
    sys.exit("Missing PORTAL_PASSWORD or SECRET_KEY. Copy .env.example to .env "
             "and fill in both values.")

for d in (LIBRARY_DIR, ACTIVE_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger("portal")
log.setLevel(logging.INFO)
_handler = RotatingFileHandler(LOGS_DIR / "portal.log",
                               maxBytes=1_000_000, backupCount=5)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_handler)
log.addHandler(logging.StreamHandler())  # also echo to console

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT NOT NULL UNIQUE,
                title       TEXT NOT NULL,
                start_date  TEXT NOT NULL,   -- YYYY-MM-DD
                end_date    TEXT NOT NULL,   -- YYYY-MM-DD, inclusive
                created_at  TEXT NOT NULL
            )
        """)


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "announcement"


def unique_library_path(start_date, title):
    """Build YYYY-MM-DD_slug.jpg, appending -2, -3, ... on collision."""
    base = f"{start_date}_{slugify(title)}"
    path = LIBRARY_DIR / f"{base}.jpg"
    n = 2
    while path.exists():
        path = LIBRARY_DIR / f"{base}-{n}.jpg"
        n += 1
    return path


def process_image(file_storage, dest_path):
    """Convert any upload to a 1920x1080 JPEG: scale to fit, center on a
    black letterbox canvas."""
    img = Image.open(file_storage)
    img = ImageOps.exif_transpose(img)  # respect phone-camera orientation
    img = img.convert("RGB")
    img.thumbnail(CANVAS_SIZE, Image.LANCZOS)  # scale to fit, keeps aspect
    canvas = Image.new("RGB", CANVAS_SIZE, (0, 0, 0))
    canvas.paste(img, ((CANVAS_SIZE[0] - img.width) // 2,
                       (CANVAS_SIZE[1] - img.height) // 2))
    canvas.save(dest_path, "JPEG", quality=90)


# ---------------------------------------------------------------------------
# Sync: make active/ exactly match today's active announcements
# ---------------------------------------------------------------------------

_sync_lock = threading.Lock()


def sync_active_folder():
    """Idempotent: copy missing active files in, remove files that shouldn't
    be there. An announcement is active when start_date <= today <= end_date
    (end date inclusive through 11:59pm local time — date-only comparison)."""
    with _sync_lock:
        today = date.today().isoformat()
        with get_db() as db:
            rows = db.execute(
                "SELECT filename FROM announcements "
                "WHERE start_date <= ? AND end_date >= ?", (today, today)
            ).fetchall()
        wanted = {row["filename"] for row in rows}
        # Ignore dotfiles (.DS_Store etc.) that Finder may create.
        present = {p.name for p in ACTIVE_DIR.iterdir()
                   if p.is_file() and not p.name.startswith(".")}

        for name in sorted(wanted - present):
            src = LIBRARY_DIR / name
            if src.exists():
                shutil.copy2(src, ACTIVE_DIR / name)
                log.info("sync: copied %s into active/", name)
            else:
                log.error("sync: library file missing for %s", name)

        for name in sorted(present - wanted):
            (ACTIVE_DIR / name).unlink()
            log.info("sync: removed %s from active/", name)


def sync_loop():
    """Background thread: re-sync every 15 minutes so slides appear/expire
    on schedule without anyone touching the app."""
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        try:
            sync_active_folder()
        except Exception:
            log.exception("sync: background sync failed")


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload cap


def status_for(row, today):
    if row["end_date"] < today:
        return "EXPIRED"
    if row["start_date"] > today:
        return "SCHEDULED"
    return "ACTIVE"


@app.route("/", methods=["GET"])
def index():
    if not session.get("authed"):
        return render_template("index.html", mode="login")
    today = date.today().isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM announcements ORDER BY end_date, start_date, title"
        ).fetchall()
    announcements = [dict(row, status=status_for(row, today)) for row in rows]
    return render_template("index.html", mode="main",
                           announcements=announcements, today=today,
                           errors=[])


@app.route("/login", methods=["POST"])
def login():
    if request.form.get("password", "") == PORTAL_PASSWORD:
        session["authed"] = True
        return redirect(url_for("index"))
    return render_template("index.html", mode="login",
                           login_error="Incorrect password."), 401


@app.route("/upload", methods=["POST"])
def upload():
    if not session.get("authed"):
        return redirect(url_for("index"))

    errors = []
    file = request.files.get("photo")
    title = request.form.get("title", "").strip()
    start_date = request.form.get("start_date", "")
    end_date = request.form.get("end_date", "")

    if not file or not file.filename:
        errors.append("Please choose a photo.")
    elif Path(file.filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        errors.append("Photo must be a JPG, PNG, or HEIC file.")
    if not title:
        errors.append("Please enter a title.")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end < start:
            errors.append("End date must be on or after the start date.")
    except ValueError:
        errors.append("Please pick valid start and end dates.")

    dest = None
    if not errors:
        dest = unique_library_path(start_date, title)
        try:
            process_image(file, dest)
        except (UnidentifiedImageError, OSError):
            errors.append("That file doesn't look like a valid image.")
            dest.unlink(missing_ok=True)

    if errors:
        today = date.today().isoformat()
        with get_db() as db:
            rows = db.execute(
                "SELECT * FROM announcements ORDER BY end_date, start_date, title"
            ).fetchall()
        announcements = [dict(row, status=status_for(row, today)) for row in rows]
        return render_template("index.html", mode="main",
                               announcements=announcements, today=today,
                               errors=errors,
                               form={"title": title, "start_date": start_date,
                                     "end_date": end_date}), 400

    with get_db() as db:
        db.execute(
            "INSERT INTO announcements "
            "(filename, title, start_date, end_date, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (dest.name, title, start_date, end_date,
             datetime.now().isoformat(timespec="seconds")))
    log.info("upload: %s (%s to %s) saved as %s",
             title, start_date, end_date, dest.name)
    sync_active_folder()
    flash(f"“{title}” uploaded. It will show {start_date} through {end_date}.")
    return redirect(url_for("index"))


@app.route("/delete/<int:announcement_id>", methods=["POST"])
def delete(announcement_id):
    if not session.get("authed"):
        return redirect(url_for("index"))
    with get_db() as db:
        row = db.execute("SELECT * FROM announcements WHERE id = ?",
                         (announcement_id,)).fetchone()
        if row:
            db.execute("DELETE FROM announcements WHERE id = ?",
                       (announcement_id,))
    if row:
        (LIBRARY_DIR / row["filename"]).unlink(missing_ok=True)
        (ACTIVE_DIR / row["filename"]).unlink(missing_ok=True)
        log.info("delete: removed %s (%s)", row["title"], row["filename"])
        sync_active_folder()
        flash(f"“{row['title']}” deleted.")
    return redirect(url_for("index"))


@app.route("/image/<path:filename>")
def image(filename):
    """Serve thumbnails straight from the library folder."""
    if not session.get("authed"):
        return redirect(url_for("index"))
    return send_from_directory(LIBRARY_DIR, filename)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from waitress import serve

    init_db()
    sync_active_folder()  # bring active/ up to date immediately
    threading.Thread(target=sync_loop, daemon=True).start()
    log.info("startup: serving on http://0.0.0.0:8080")
    serve(app, host="0.0.0.0", port=8080)
