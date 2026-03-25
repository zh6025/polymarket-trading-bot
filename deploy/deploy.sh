#!/usr/bin/env bash
# deploy/deploy.sh — Full lifecycle deploy (pull + restart)
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/polymarket-bot}"
cd "$DEPLOY_DIR"

echo "=== Deploying Polymarket Bot ==="

git pull origin main
docker-compose down --remove-orphans || true
docker-compose build --no-cache
docker-compose up -d bot

echo "✅ Bot deployed and running."
docker-compose ps
