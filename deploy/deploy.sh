#!/bin/bash
# =============================================================================
# Polymarket Trading Bot - Deployment Script
# =============================================================================
# Clones or updates the project, validates the environment, builds the Docker
# image, and starts all services.
#
# Usage: ./deploy.sh [--skip-backup] [--no-pull]
# =============================================================================

set -euo pipefail

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_section() { echo -e "\n${BLUE}==== $* ====${NC}"; }

# ---- Defaults ----
REPO_URL="${REPO_URL:-https://github.com/zh6025/polymarket-trading-bot.git}"
BOT_DIR="${BOT_DIR:-/opt/polymarket-trading-bot}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$BOT_DIR/.env}"
SKIP_BACKUP=false
NO_PULL=false

# ---- Parse arguments ----
for arg in "$@"; do
    case $arg in
        --skip-backup) SKIP_BACKUP=true ;;
        --no-pull)     NO_PULL=true ;;
    esac
done

log_section "Polymarket Bot - Deployment"
log_info "Repository : $REPO_URL"
log_info "Directory  : $BOT_DIR"
log_info "Branch     : $BRANCH"
log_info "Compose    : $COMPOSE_FILE"
log_info "Date/Time  : $(date)"

# =============================================================================
# 1. Clone or update repository
# =============================================================================
log_section "Repository Sync"
if [[ -d "$BOT_DIR/.git" ]]; then
    if [[ "$NO_PULL" == "false" ]]; then
        log_info "Updating existing repository..."
        cd "$BOT_DIR"
        git fetch origin
        git checkout "$BRANCH"
        git reset --hard "origin/$BRANCH"
        log_info "Repository updated to $(git rev-parse --short HEAD)"
    else
        log_warn "--no-pull specified, skipping git update."
        cd "$BOT_DIR"
    fi
else
    log_info "Cloning repository..."
    git clone --branch "$BRANCH" "$REPO_URL" "$BOT_DIR"
    cd "$BOT_DIR"
    log_info "Repository cloned to $(git rev-parse --short HEAD)"
fi

# =============================================================================
# 2. Environment file validation
# =============================================================================
log_section "Environment Configuration"
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$BOT_DIR/deploy/.env.production" ]]; then
        log_warn ".env not found. Copying from deploy/.env.production ..."
        cp "$BOT_DIR/deploy/.env.production" "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        log_warn "Edit $ENV_FILE and add your real API keys before starting!"
    else
        log_error ".env file not found at $ENV_FILE"
        log_error "Create one from: cp deploy/.env.production .env && nano .env"
        exit 1
    fi
fi

REQUIRED_VARS=("API_KEY")
MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
    val=$(grep -E "^${var}=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' || true)
    if [[ -z "$val" || "$val" == "<"*">" || "$val" == "your-"* ]]; then
        MISSING+=("$var")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    log_warn "The following variables appear to be placeholders in $ENV_FILE:"
    for v in "${MISSING[@]}"; do
        log_warn "  - $v"
    done
    log_warn "Proceeding anyway — set DRY_RUN=true in .env for safe testing."
fi
log_info "Environment file: $ENV_FILE"

# =============================================================================
# 3. Pre-deploy backup (unless skipped)
# =============================================================================
if [[ "$SKIP_BACKUP" == "false" && -f "$BOT_DIR/deploy/backup.sh" ]]; then
    log_section "Pre-deploy Backup"
    bash "$BOT_DIR/deploy/backup.sh" || log_warn "Backup failed — continuing deployment."
fi

# =============================================================================
# 4. Build Docker image
# =============================================================================
log_section "Docker Build"
cd "$BOT_DIR"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build --no-cache
log_info "Docker image built successfully."

# =============================================================================
# 5. Stop old containers
# =============================================================================
log_section "Stopping Old Containers"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true
log_info "Old containers stopped."

# =============================================================================
# 6. Start services
# =============================================================================
log_section "Starting Services"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d
log_info "Services started."

# =============================================================================
# 7. Health check
# =============================================================================
log_section "Post-deploy Health Check"
sleep 10
CONTAINER_NAME="${CONTAINER_NAME:-polymarket-bot}"
if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q "$CONTAINER_NAME"; then
    log_info "Container '$CONTAINER_NAME' is running."
else
    log_error "Container '$CONTAINER_NAME' is NOT running!"
    log_error "Check logs: docker compose -f $COMPOSE_FILE logs bot"
    exit 1
fi

# =============================================================================
# 8. Show status
# =============================================================================
log_section "Deployment Complete"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps
log_info "View logs : docker compose -f $COMPOSE_FILE logs -f bot"
log_info "Stop bot  : docker compose -f $COMPOSE_FILE down"
log_info "Deployed at $(date)"
