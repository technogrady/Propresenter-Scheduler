# Announcement Slides Portal

A tiny web app volunteers use to upload announcement slides from their phones.
Each upload gets a start and end date. The app keeps `~/Announcements/active/`
containing **only** the slides whose date range includes today — ProPresenter
watches that folder as a Smart Playlist. The app never talks to ProPresenter
directly.

Every upload (JPG, PNG, or iPhone HEIC) is converted to a 1920x1080 JPEG,
letterboxed on black.

## Folders

Everything lives under `~/Announcements/` (created automatically):

| Path        | Purpose                                          |
|-------------|--------------------------------------------------|
| `library/`  | Permanent copies of every processed slide        |
| `active/`   | Synced folder ProPresenter watches               |
| `logs/`     | `portal.log` (rotating) — uploads, deletes, sync |
| `data.db`   | SQLite database                                  |

## Setup

The quick way:

```bash
cd ~/ProPresenter-Scheduler
./setup.sh              # venv + dependencies + .env
venv/bin/python app.py  # test it manually (Ctrl-C to stop)
```

Then open http://localhost:8080 and sign in. The default password is
`propresenterscheduler` — change it in `.env` before sharing the link.

Or do the same steps by hand:

```bash
cd ~/ProPresenter-Scheduler

# 1. Create a virtualenv and install dependencies
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 2. Configure the password and secret key
cp .env.example .env
open -e .env    # set PORTAL_PASSWORD and SECRET_KEY, then save

# 3. Test it manually (Ctrl-C to stop)
venv/bin/python app.py
```

## Run automatically at login (LaunchAgent)

```bash
./setup.sh --install
```

That rewrites the plist paths for this machine, copies it to
`~/Library/LaunchAgents/`, and loads it. Or by hand:

```bash
cp com.church.announcements.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.church.announcements.plist
```

The app now starts at login and restarts if it crashes (`KeepAlive`).

To stop it or apply code changes:

```bash
launchctl unload ~/Library/LaunchAgents/com.church.announcements.plist
launchctl load   ~/Library/LaunchAgents/com.church.announcements.plist
```

> If your username or project folder differs from
> `/Users/gradenlemasters/ProPresenter-Scheduler`, edit the paths inside the
> plist before copying it.

## ProPresenter setup

In ProPresenter, create a **Smart Playlist** (Playlist ▸ New Smart Playlist)
and point it at:

```
~/Announcements/active
```

ProPresenter picks up changes to that folder automatically. The portal
re-syncs it on startup, after every upload or delete, and every 15 minutes —
so slides appear on their start date and disappear the day after their end
date without anyone touching the Mac. An announcement's end date is
**inclusive**: it stays up through 11:59pm that day.

## Volunteers: how to reach the portal

From any phone or computer on the same network:

```
http://<mac-name>.local:8080
```

Find the Mac's name in **System Settings ▸ General ▸ Sharing** — the
"local hostname" is shown near the top (e.g. `http://sanctuary-mac.local:8080`).
Everyone signs in with the one shared password from `.env`.

## Logs

- App log: `~/Announcements/logs/portal.log` (rotates at 1 MB, keeps 5 files)
- LaunchAgent output: `~/Announcements/logs/launchd.out.log` / `launchd.err.log`

```bash
tail -f ~/Announcements/logs/portal.log
```
# Propresenter-Scheduler
