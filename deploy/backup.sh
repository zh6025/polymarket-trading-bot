#!/usr/bin/env bash
# deploy/backup.sh — SQLite + config backup with 7-day rotation
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/polymarket-bot}"
BACKUP_DIR="${BACKUP_DIR:-/opt/polymarket-bot-backups}"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup databases
for db in bot_data.db simulate_data.db; do
    if [ -f "$DEPLOY_DIR/$db" ]; then
        cp "$DEPLOY_DIR/$db" "$BACKUP_DIR/${db%.db}-$DATE.db"
        echo "Backed up $db"
    fi
done

# Backup bot state
for f in bot_state.json simulate_state.json .env; do
    if [ -f "$DEPLOY_DIR/$f" ]; then
        cp "$DEPLOY_DIR/$f" "$BACKUP_DIR/${f}-$DATE"
    fi
done

# Rotate: keep last 7 days
find "$BACKUP_DIR" -mtime +7 -delete
echo "✅ Backup complete: $BACKUP_DIR"
