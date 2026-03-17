#!/bin/bash
# =============================================================================
# Polymarket Trading Bot - Backup Script
# =============================================================================
# Backs up the SQLite database, .env config, and log files.
# Retains the most recent 30 daily backups and auto-removes older ones.
#
# Usage:   ./backup.sh
# Cron:    0 2 * * * /opt/polymarket-trading-bot/deploy/backup.sh
# =============================================================================

set -euo pipefail

# ---- Configuration ----
BOT_DIR="${BOT_DIR:-/opt/polymarket-trading-bot}"
BACKUP_ROOT="${BACKUP_ROOT:-$BOT_DIR/backups}"
CONTAINER_NAME="${CONTAINER_NAME:-polymarket-bot}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"

# ---- Colors ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

log_info "Starting backup at $TIMESTAMP"
log_info "Backup directory: $BACKUP_DIR"

mkdir -p "$BACKUP_DIR"

# =============================================================================
# 1. Database backup (SQLite from container or host mount)
# =============================================================================
log_info "Backing up database..."
DB_BACKED=false

# Try to copy from running container first
if docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" \
        --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    docker cp "${CONTAINER_NAME}:/app/data/bot_data.db" "$BACKUP_DIR/bot_data.db" 2>/dev/null \
        && { log_info "Database copied from container."; DB_BACKED=true; } \
        || log_warn "Could not copy database from container (file may not exist yet)."
fi

# Fall back to host-mounted file
if [[ "$DB_BACKED" == "false" && -f "$BOT_DIR/bot_data.db" ]]; then
    cp "$BOT_DIR/bot_data.db" "$BACKUP_DIR/bot_data.db"
    log_info "Database copied from host mount."
    DB_BACKED=true
fi

if [[ "$DB_BACKED" == "false" ]]; then
    log_warn "No database file found — skipping database backup."
fi

# =============================================================================
# 2. Configuration backup (.env)
# =============================================================================
log_info "Backing up configuration..."
if [[ -f "$BOT_DIR/.env" ]]; then
    cp "$BOT_DIR/.env" "$BACKUP_DIR/.env"
    chmod 600 "$BACKUP_DIR/.env"
    log_info ".env backed up."
else
    log_warn ".env not found at $BOT_DIR/.env — skipping."
fi

# =============================================================================
# 3. Log backup
# =============================================================================
log_info "Backing up logs..."
if [[ -d "$BOT_DIR/logs" ]] && compgen -G "$BOT_DIR/logs/*.log" > /dev/null 2>&1; then
    cp -r "$BOT_DIR/logs" "$BACKUP_DIR/logs"
    log_info "Logs backed up."
else
    log_warn "No log files found — skipping log backup."
fi

# Also capture recent Docker logs
if docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" \
        --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    docker logs --tail=5000 "$CONTAINER_NAME" > "$BACKUP_DIR/docker-recent.log" 2>&1 \
        && log_info "Recent Docker logs saved." \
        || log_warn "Could not save Docker logs."
fi

# =============================================================================
# 4. Compress backup
# =============================================================================
log_info "Compressing backup..."
ARCHIVE="$BACKUP_ROOT/backup_${TIMESTAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$BACKUP_ROOT" "$TIMESTAMP"
rm -rf "$BACKUP_DIR"
log_info "Backup archive: $ARCHIVE ($(du -sh "$ARCHIVE" | cut -f1))"

# =============================================================================
# 5. Backup rotation — keep only the last RETAIN_DAYS backups
# =============================================================================
log_info "Rotating backups (keeping last $RETAIN_DAYS)..."
BACKUP_COUNT=$(find "$BACKUP_ROOT" -maxdepth 1 -name 'backup_*.tar.gz' | wc -l)
if [[ "$BACKUP_COUNT" -gt "$RETAIN_DAYS" ]]; then
    REMOVE_COUNT=$(( BACKUP_COUNT - RETAIN_DAYS ))
    find "$BACKUP_ROOT" -maxdepth 1 -name 'backup_*.tar.gz' \
        | sort | head -n "$REMOVE_COUNT" | xargs rm -f
    log_info "Removed $REMOVE_COUNT old backup(s)."
fi

REMAINING=$(find "$BACKUP_ROOT" -maxdepth 1 -name 'backup_*.tar.gz' | wc -l)
log_info "Total backups retained: $REMAINING"

# =============================================================================
# Done
# =============================================================================
log_info "Backup completed successfully: $ARCHIVE"
