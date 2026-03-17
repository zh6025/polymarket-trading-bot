#!/bin/bash
# =============================================================================
# Polymarket Trading Bot - Health Check Script
# =============================================================================
# Checks container status, API connectivity, log errors, and resource usage.
# Designed to be run by cron every 5 minutes.
#
# Usage:   ./health-check.sh
# Cron:    */5 * * * * /opt/polymarket-trading-bot/deploy/health-check.sh
# =============================================================================

set -uo pipefail

# ---- Configuration ----
CONTAINER_NAME="${CONTAINER_NAME:-polymarket-bot}"
BOT_DIR="${BOT_DIR:-/opt/polymarket-trading-bot}"
LOG_FILE="${LOG_FILE:-$BOT_DIR/logs/health-check.log}"
COMPOSE_FILE="${COMPOSE_FILE:-$BOT_DIR/deploy/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$BOT_DIR/.env}"

# Alert thresholds
MEM_THRESHOLD_PCT=85   # % container memory used before alert
CPU_THRESHOLD_PCT=90   # % host CPU used before alert
DISK_THRESHOLD_PCT=85  # % disk used before alert
ERROR_LOG_LINES=200    # recent log lines to scan for errors
MAX_RESTARTS=5         # restart count before alerting

# Alert method: "log" | "echo" | "email"
ALERT_METHOD="${ALERT_METHOD:-log}"
ALERT_EMAIL="${ALERT_EMAIL:-}"

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
ISSUES=()

# ---- Ensure log directory ----
mkdir -p "$(dirname "$LOG_FILE")"

# ---- Helpers ----
log()   { echo "[$TIMESTAMP] $*" | tee -a "$LOG_FILE"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; log "[OK] $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; log "[WARN] $*"; ISSUES+=("$*"); }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; log "[FAIL] $*"; ISSUES+=("$*"); }

send_alert() {
    local subject="$1"
    local body="$2"
    case "$ALERT_METHOD" in
        email)
            if [[ -n "$ALERT_EMAIL" ]] && command -v mail &>/dev/null; then
                echo "$body" | mail -s "$subject" "$ALERT_EMAIL"
            fi
            ;;
        log)
            log "[ALERT] $subject | $body"
            ;;
        *)
            echo "[ALERT] $subject"
            ;;
    esac
}

# =============================================================================
# 1. Container status
# =============================================================================
echo ""
echo "===== Health Check: $TIMESTAMP ====="

log "Checking container status..."
if docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" \
        --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    ok "Container '$CONTAINER_NAME' is running."
else
    fail "Container '$CONTAINER_NAME' is NOT running!"
    # Attempt auto-restart
    if [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]]; then
        log "Attempting to restart via docker compose..."
        docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d \
            && log "Restart command issued." \
            || log "Restart failed."
    fi
    send_alert "Polymarket Bot DOWN" \
        "Container $CONTAINER_NAME is not running on $(hostname). Auto-restart attempted at $TIMESTAMP."
fi

# =============================================================================
# 2. Container restart count
# =============================================================================
RESTARTS=$(docker inspect --format '{{.RestartCount}}' "$CONTAINER_NAME" 2>/dev/null || echo "0")
if [[ "$RESTARTS" -ge "$MAX_RESTARTS" ]]; then
    warn "Container has restarted $RESTARTS times (threshold: $MAX_RESTARTS)."
    send_alert "Polymarket Bot Restart Loop" \
        "Container $CONTAINER_NAME has restarted $RESTARTS times. Check logs immediately."
else
    ok "Restart count: $RESTARTS"
fi

# =============================================================================
# 3. Memory usage (only if container is running)
# =============================================================================
if docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" \
        --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    MEM_USAGE=$(docker stats "$CONTAINER_NAME" --no-stream --format "{{.MemPerc}}" 2>/dev/null \
        | tr -d '%' || echo "0")
    # Strip decimal portion for integer comparison
    MEM_INT=${MEM_USAGE%.*}
    MEM_INT=${MEM_INT:-0}
    if [[ "$MEM_INT" -ge "$MEM_THRESHOLD_PCT" ]]; then
        warn "High memory usage: ${MEM_USAGE}% (threshold: ${MEM_THRESHOLD_PCT}%)"
        send_alert "Polymarket Bot High Memory" \
            "Memory usage is ${MEM_USAGE}% on $(hostname)."
    else
        ok "Memory usage: ${MEM_USAGE}%"
    fi
fi

# =============================================================================
# 4. Host CPU usage
# Read two samples from /proc/stat (100 ms apart) — fast and portable.
# =============================================================================
read_cpu() { awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8, $5}' /proc/stat; }
read1=$(read_cpu); sleep 0.1; read2=$(read_cpu)
TOTAL1=$(echo "$read1" | awk '{print $1}'); IDLE1=$(echo "$read1" | awk '{print $2}')
TOTAL2=$(echo "$read2" | awk '{print $1}'); IDLE2=$(echo "$read2" | awk '{print $2}')
DELTA_TOTAL=$(( TOTAL2 - TOTAL1 ))
DELTA_IDLE=$(( IDLE2 - IDLE1 ))
if [[ "$DELTA_TOTAL" -gt 0 ]]; then
    CPU_USED=$(( (DELTA_TOTAL - DELTA_IDLE) * 100 / DELTA_TOTAL ))
else
    CPU_USED=0
fi
if [[ "$CPU_USED" -ge "$CPU_THRESHOLD_PCT" ]]; then
    warn "High host CPU usage: ${CPU_USED}% (threshold: ${CPU_THRESHOLD_PCT}%)"
else
    ok "Host CPU usage: ${CPU_USED}%"
fi

# =============================================================================
# 5. Disk usage
# =============================================================================
DISK_PCT=$(df "$BOT_DIR" | tail -1 | awk '{print $5}' | tr -d '%' 2>/dev/null || echo "0")
if [[ "$DISK_PCT" -ge "$DISK_THRESHOLD_PCT" ]]; then
    warn "High disk usage: ${DISK_PCT}% on $BOT_DIR (threshold: ${DISK_THRESHOLD_PCT}%)"
    send_alert "Polymarket Bot Disk Space" \
        "Disk usage is ${DISK_PCT}% on $(hostname):${BOT_DIR}."
else
    ok "Disk usage: ${DISK_PCT}%"
fi

# =============================================================================
# 6. Log error analysis
# =============================================================================
if docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" \
        --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    ERROR_COUNT=$(docker logs --tail="$ERROR_LOG_LINES" "$CONTAINER_NAME" 2>&1 \
        | grep -ciE '\b(ERROR|CRITICAL|EXCEPTION|Traceback)\b' || true)
    CRITICAL_COUNT=$(docker logs --tail="$ERROR_LOG_LINES" "$CONTAINER_NAME" 2>&1 \
        | grep -ciE '\b(CRITICAL|Traceback)\b' || true)

    if [[ "$CRITICAL_COUNT" -gt 0 ]]; then
        warn "Found $CRITICAL_COUNT CRITICAL/Traceback entries in last $ERROR_LOG_LINES log lines."
        LAST_CRITICAL=$(docker logs --tail="$ERROR_LOG_LINES" "$CONTAINER_NAME" 2>&1 \
            | grep -E '\b(CRITICAL|Traceback)\b' | tail -3)
        send_alert "Polymarket Bot Critical Error" \
            "Found $CRITICAL_COUNT critical errors on $(hostname):\n$LAST_CRITICAL"
    elif [[ "$ERROR_COUNT" -gt 0 ]]; then
        warn "Found $ERROR_COUNT ERROR entries in last $ERROR_LOG_LINES log lines."
    else
        ok "No errors in last $ERROR_LOG_LINES log lines."
    fi
fi

# =============================================================================
# 7. API connectivity (basic HTTPS check to Polymarket)
# =============================================================================
API_HOST="${API_HOST:-clob.polymarket.com}"
if curl -fsSL --max-time 10 "https://${API_HOST}/markets" -o /dev/null 2>/dev/null; then
    ok "API connectivity to $API_HOST: OK"
else
    warn "Cannot reach $API_HOST — possible network or API issue."
    send_alert "Polymarket API Unreachable" \
        "Cannot reach $API_HOST from $(hostname) at $TIMESTAMP."
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
if [[ ${#ISSUES[@]} -eq 0 ]]; then
    echo -e "${GREEN}All checks passed.${NC}"
    log "Health check passed — no issues."
else
    echo -e "${YELLOW}Health check finished with ${#ISSUES[@]} issue(s):${NC}"
    for issue in "${ISSUES[@]}"; do
        echo -e "  ${RED}•${NC} $issue"
    done
    log "Health check finished with ${#ISSUES[@]} issue(s)."
    exit 1
fi
