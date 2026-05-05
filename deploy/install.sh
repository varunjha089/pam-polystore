#!/usr/bin/env bash
# Deploy PAM systemd services and nginx config.
# Run once on a fresh server after cloning the repo.
# Usage: sudo bash deploy/install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/3] Installing systemd service files..."
sudo cp "$REPO_DIR/deploy/pam-api.service" /etc/systemd/system/
sudo cp "$REPO_DIR/deploy/pam-ui.service"  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pam-api.service pam-ui.service
echo "      pam-api.service and pam-ui.service enabled"

echo "[2/3] Installing nginx config..."
sudo cp "$REPO_DIR/deploy/nginx.conf" /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
echo "      nginx reloaded"

echo "[3/3] Starting services..."
sudo systemctl start pam-api.service
sleep 3
sudo systemctl start pam-ui.service
sleep 3

sudo systemctl status pam-api.service --no-pager | grep -E "Active:"
sudo systemctl status pam-ui.service  --no-pager | grep -E "Active:"
echo ""
echo "Done. Visit http://$(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
