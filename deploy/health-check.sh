#!/usr/bin/env bash
# deploy/health-check.sh — Cron-friendly health check
# Exits 0 if healthy, 1 if unhealthy (triggers restart)
set -euo pipefail

CONTAINER="${BOT_CONTAINER:-polymarket-bot}"

if ! docker inspect --format='{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    echo "UNHEALTHY: container $CONTAINER not running — restarting..."
    docker start "$CONTAINER"
    exit 1
fi

echo "HEALTHY: $CONTAINER is running."
exit 0
