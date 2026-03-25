#!/usr/bin/env bash
# deploy/setup-linode.sh — Bootstrap a fresh Ubuntu 22.04 Linode server
set -euo pipefail

echo "=== Polymarket Bot — Linode Server Bootstrap ==="

apt-get update -y && apt-get upgrade -y
apt-get install -y python3 python3-pip python3-venv git docker.io docker-compose curl sqlite3

# Enable Docker
systemctl enable docker && systemctl start docker

# Clone repo (customize URL)
REPO_URL="${REPO_URL:-https://github.com/zh6025/polymarket-trading-bot.git}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/polymarket-bot}"

if [ ! -d "$DEPLOY_DIR" ]; then
    git clone "$REPO_URL" "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"
cp -n .env.example .env || true
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

echo ""
echo "✅ Server bootstrapped."
echo "   Next: edit $DEPLOY_DIR/.env with your API keys, then run deploy/deploy.sh"
