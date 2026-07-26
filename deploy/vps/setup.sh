#!/usr/bin/env bash
# Reference setup script for a small VPS (Ubuntu/Debian assumed).
#
# This is a TEMPLATE for you to read and run yourself on the actual server —
# it is not executed by this repo or by any agent session, and nothing in
# this codebase invokes it automatically. Review every line (paths, domain,
# package versions) before running.
#
# Usage on the server, as a user with sudo:
#   git clone <your-repo-url> /opt/english-essay
#   cd /opt/english-essay
#   sudo bash deploy/vps/setup.sh

set -euo pipefail

APP_DIR="/opt/english-essay"

sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv nginx certbot python3-certbot-nginx default-jre-headless

cd "$APP_DIR"
python3.11 -m venv venv
venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
    echo "Creating .env — edit it now to set real SESSION_SECRET_KEY / ENCRYPTION_KEY / APP_ENV=production"
    {
        echo "DATABASE_URL=sqlite:////opt/english-essay/app.db"
        echo "SESSION_SECRET_KEY=$(venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
        echo "ENCRYPTION_KEY=$(venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
        echo "APP_ENV=production"
    } > .env
    chmod 600 .env
fi

venv/bin/alembic upgrade head

sudo cp deploy/vps/english-essay.service /etc/systemd/system/english-essay.service
sudo systemctl daemon-reload
sudo systemctl enable --now english-essay

sudo cp deploy/vps/nginx.conf /etc/nginx/sites-available/english-essay
sudo ln -sf /etc/nginx/sites-available/english-essay /etc/nginx/sites-enabled/english-essay
sudo nginx -t && sudo systemctl reload nginx

echo "Now point your domain's DNS A/AAAA record at this server, edit"
echo "server_name in /etc/nginx/sites-available/english-essay, then run:"
echo "  sudo certbot --nginx -d your-domain.example"
