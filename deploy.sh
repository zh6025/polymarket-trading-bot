#!/usr/bin/env bash
# =============================================================================
# deploy.sh – One-command bootstrap for the Polymarket Trading Bot
#             on a fresh Ubuntu 22.04 / 24.04 VPS
#
# Usage (run as root or with sudo on a brand-new VPS):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/zh6025/polymarket-trading-bot/main/deploy.sh)
#
# Or if you have already cloned the repo:
#
#   chmod +x deploy.sh && ./deploy.sh
#
# What this script does:
#   1. Installs Docker CE + Docker Compose plugin
#   2. Hardens the firewall (ufw)
#   3. Creates /opt/polymarket-bot and clones / pulls the repo
#   4. Copies .env.dry_run → .env if no .env exists yet
#   5. Creates a systemd service so the bot restarts after reboots
#   6. Starts the bot in DRY RUN mode
#
# After the script finishes:
#   • Edit /opt/polymarket-bot/.env with your real credentials
#   • Run:  systemctl restart polymarket-bot
# =============================================================================

set -euo pipefail

REPO_URL="https://github.com/zh6025/polymarket-trading-bot.git"
INSTALL_DIR="/opt/polymarket-bot"
SERVICE_NAME="polymarket-bot"
BOT_USER="polybot"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── must be root ──────────────────────────────────────────────────────────────
[[ "$(id -u)" -eq 0 ]] || die "Please run as root:  sudo bash deploy.sh"

echo -e "\n${BOLD}${CYAN}════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Polymarket Trading Bot – VPS Deployment Script${NC}"
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════${NC}\n"

# ── 1. System update ──────────────────────────────────────────────────────────
info "Updating system packages…"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq git curl ufw ca-certificates gnupg lsb-release

# ── 2. Install Docker CE ──────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
    success "Docker already installed: $(docker --version)"
else
    info "Installing Docker CE…"
    install -m 0755 -d /etc/apt/keyrings

    # Download Docker's GPG key and verify its fingerprint before trusting it.
    # Official Docker GPG key fingerprint (as published on https://docs.docker.com/engine/install/ubuntu/):
    # 9DC8 5822 9FC7 DD38 854A  E2D8 8D81 803C 0EBF CD88
    DOCKER_GPG_URL="https://download.docker.com/linux/ubuntu/gpg"
    DOCKER_GPG_FILE="/etc/apt/keyrings/docker.gpg"
    EXPECTED_FINGERPRINT="9DC8 5822 9FC7 DD38 854A  E2D8 8D81 803C 0EBF CD88"

    curl -fsSL "${DOCKER_GPG_URL}" | gpg --dearmor -o "${DOCKER_GPG_FILE}"
    chmod a+r "${DOCKER_GPG_FILE}"

    ACTUAL_FINGERPRINT=$(gpg --no-default-keyring --keyring "${DOCKER_GPG_FILE}" \
        --fingerprint 2>/dev/null | grep -A1 "pub" | tail -1 | tr -d ' ')
    EXPECTED_STRIPPED=$(echo "${EXPECTED_FINGERPRINT}" | tr -d ' ')

    if [[ "${ACTUAL_FINGERPRINT}" != "${EXPECTED_STRIPPED}" ]]; then
        rm -f "${DOCKER_GPG_FILE}"
        die "Docker GPG key fingerprint mismatch! Expected: ${EXPECTED_FINGERPRINT}\nActual:   ${ACTUAL_FINGERPRINT}\nAborting for security."
    fi
    success "Docker GPG key fingerprint verified"

    echo "deb [arch=$(dpkg --print-architecture) \
signed-by=${DOCKER_GPG_FILE}] \
https://download.docker.com/linux/ubuntu \
$(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    systemctl enable --now docker
    success "Docker installed: $(docker --version)"
fi

# ── 3. Firewall ───────────────────────────────────────────────────────────────
info "Configuring firewall (ufw)…"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh        # port 22
ufw --force enable
success "Firewall enabled (SSH allowed, all other inbound blocked)"

# ── 4. Dedicated system user ──────────────────────────────────────────────────
if ! id "${BOT_USER}" &>/dev/null; then
    info "Creating system user '${BOT_USER}'…"
    useradd --system --shell /bin/false --home "${INSTALL_DIR}" "${BOT_USER}"
    usermod -aG docker "${BOT_USER}"
fi

# ── 5. Clone or update the repo ───────────────────────────────────────────────
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing repo at ${INSTALL_DIR}…"
    git -C "${INSTALL_DIR}" pull --ff-only
    success "Repo updated"
else
    info "Cloning repo into ${INSTALL_DIR}…"
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
    success "Repo cloned"
fi

chown -R "${BOT_USER}:${BOT_USER}" "${INSTALL_DIR}"

# ── 6. Environment file ───────────────────────────────────────────────────────
ENV_FILE="${INSTALL_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    info "No .env found – copying .env.dry_run as starting point…"
    cp "${INSTALL_DIR}/.env.dry_run" "${ENV_FILE}"
    chown "${BOT_USER}:${BOT_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    warn "Bot will start in DRY RUN mode."
    warn "Edit ${ENV_FILE} to set your credentials, then:"
    warn "  systemctl restart ${SERVICE_NAME}"
else
    success ".env already exists – not overwriting"
fi

# ── 7. Systemd service ────────────────────────────────────────────────────────
info "Installing systemd service '${SERVICE_NAME}'…"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Polymarket BTC Up/Down 5-Minute Trading Bot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStartPre=/usr/bin/docker compose pull --quiet || true
ExecStart=/usr/bin/docker compose up --build
ExecStop=/usr/bin/docker compose down
Restart=on-failure
RestartSec=30
TimeoutStartSec=120
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

# ── 8. Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Deployment complete!  部署完成！${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Bot directory : ${BOLD}${INSTALL_DIR}${NC}"
echo -e "  Config file   : ${BOLD}${ENV_FILE}${NC}"
echo -e "  Service name  : ${BOLD}${SERVICE_NAME}${NC}"
echo ""
echo -e "${YELLOW}  Next steps:${NC}"
echo -e "  1. Edit your credentials:"
echo -e "     ${BOLD}nano ${ENV_FILE}${NC}"
echo -e ""
echo -e "  2. For live trading, set TRADING_MODE=live in .env, then:"
echo -e "     ${BOLD}systemctl restart ${SERVICE_NAME}${NC}"
echo -e ""
echo -e "  3. View live logs:"
echo -e "     ${BOLD}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "     or:  ${BOLD}cd ${INSTALL_DIR} && docker compose logs -f${NC}"
echo -e ""
echo -e "  4. View trading data:"
echo -e "     ${BOLD}cd ${INSTALL_DIR} && python view_trades.py${NC}"
echo ""
