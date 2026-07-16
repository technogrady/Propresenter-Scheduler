#!/bin/bash
# One-time setup for the Announcement Slides portal.
# Usage:  ./setup.sh            (setup + start manually with: venv/bin/python app.py)
#         ./setup.sh --install  (also install the LaunchAgent so it runs at login)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Creating virtualenv"
python3 -m venv venv

echo "==> Installing dependencies"
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt

# Create .env on first run with the default password and a random secret key.
if [ ! -f .env ]; then
    echo "==> Creating .env"
    cat > .env <<EOF
PORTAL_PASSWORD=propresenterscheduler
SECRET_KEY=$(venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
EOF
    echo "    Default password is 'propresenterscheduler' — edit .env to change it."
else
    echo "==> .env already exists, leaving it alone"
fi

# Optionally install the LaunchAgent so the app runs at login and stays up.
if [ "${1:-}" = "--install" ]; then
    echo "==> Installing LaunchAgent"
    PLIST=~/Library/LaunchAgents/com.church.announcements.plist
    # Rewrite the plist paths to match wherever this repo actually lives.
    sed "s|/Users/gradenlemasters/ProPresenter-Scheduler|$(pwd)|g; s|/Users/gradenlemasters|$HOME|g" \
        com.church.announcements.plist > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "    Portal is running: http://$(scutil --get LocalHostName).local:8080"
else
    echo
    echo "Done. Start the portal with:   venv/bin/python app.py"
    echo "Or run at login with:          ./setup.sh --install"
fi
