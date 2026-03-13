#!/usr/bin/env bash
# =============================================================================
# vultr-startup.sh  –  Vultr "Startup Script" for the Polymarket Trading Bot
# =============================================================================
#
# HOW TO USE (在 Vultr 网站上的操作):
#
#   1. Log in to https://my.vultr.com
#   2. Left sidebar → "Startup Scripts" → "Add Startup Script"
#   3. Name: polymarket-bot-setup
#      Type: Boot
#      Script: (paste this entire file)
#   4. Click "Save"
#   5. Create a new server:
#        OS    : Ubuntu 22.04 LTS (or 24.04 LTS)
#        Plan  : Regular Cloud Compute – $6/mo (1 vCPU / 1 GB / 25 GB SSD)
#        Region: New Jersey  ← closest to Polymarket's CLOB servers
#        Startup Script: polymarket-bot-setup  ← select the script you just saved
#   6. Click "Deploy Now"
#
# The bot will be fully installed and running in DRY RUN mode by the time
# the server finishes booting (~2–3 minutes).
#
# After the server is ready:
#   ssh root@YOUR_SERVER_IP
#   tail -f /var/log/polymarket-bot-setup.log   # see what the script did
#   nano /opt/polymarket-bot/.env               # fill in your credentials
#   systemctl restart polymarket-bot            # go live
# =============================================================================

set -euo pipefail

# ── logging – everything goes to both console and a logfile ──────────────────
LOG_FILE="/var/log/polymarket-bot-setup.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

REPO_URL="https://github.com/zh6025/polymarket-trading-bot.git"
INSTALL_DIR="/opt/polymarket-bot"
SERVICE_NAME="polymarket-bot"
BOT_USER="polybot"

echo "============================================================"
echo " Polymarket Trading Bot – Vultr Startup Script"
echo " Started at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo " Log file  : ${LOG_FILE}"
echo "============================================================"

# ── wait for networking (cloud-init can run before the network is up) ─────────
echo "[1/8] Waiting for network connectivity…"
for i in $(seq 1 30); do
    if curl -fsSL --max-time 5 https://github.com > /dev/null 2>&1; then
        echo "      Network ready after ${i}s"
        break
    fi
    sleep 1
done

# ── system update ─────────────────────────────────────────────────────────────
echo "[2/8] Updating system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq -o Dpkg::Options::="--force-confdef" \
                        -o Dpkg::Options::="--force-confold"
apt-get install -y -qq git curl ufw ca-certificates gnupg lsb-release

# ── install Docker CE ─────────────────────────────────────────────────────────
echo "[3/8] Installing Docker CE…"
if command -v docker &>/dev/null; then
    echo "      Docker already installed: $(docker --version)"
else
    install -m 0755 -d /etc/apt/keyrings

    # Verify Docker GPG key fingerprint before trusting it.
    # Official fingerprint: 9DC8 5822 9FC7 DD38 854A  E2D8 8D81 803C 0EBF CD88
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
        echo "ERROR: Docker GPG fingerprint mismatch – aborting for security."
        echo "  Expected : ${EXPECTED_FINGERPRINT}"
        echo "  Actual   : ${ACTUAL_FINGERPRINT}"
        exit 1
    fi
    echo "      Docker GPG key fingerprint verified"

    echo "deb [arch=$(dpkg --print-architecture) signed-by=${DOCKER_GPG_FILE}] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    systemctl enable --now docker
    echo "      Docker installed: $(docker --version)"
fi

# ── firewall ──────────────────────────────────────────────────────────────────
echo "[4/8] Configuring firewall…"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh          # port 22 – keep SSH access
ufw --force enable
echo "      Firewall enabled: SSH only (outbound unrestricted)"

# ── dedicated bot user ────────────────────────────────────────────────────────
echo "[5/8] Creating system user '${BOT_USER}'…"
if ! id "${BOT_USER}" &>/dev/null; then
    useradd --system --shell /bin/false --home "${INSTALL_DIR}" "${BOT_USER}"
    usermod -aG docker "${BOT_USER}"
    echo "      User '${BOT_USER}' created"
else
    echo "      User '${BOT_USER}' already exists"
fi

# ── clone or update repo ──────────────────────────────────────────────────────
echo "[6/8] Cloning repository…"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git -C "${INSTALL_DIR}" pull --ff-only
    echo "      Repo updated"
else
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
    echo "      Repo cloned to ${INSTALL_DIR}"
fi
chown -R "${BOT_USER}:${BOT_USER}" "${INSTALL_DIR}"

# ── environment file ──────────────────────────────────────────────────────────
echo "[7/8] Setting up .env…"
ENV_FILE="${INSTALL_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${INSTALL_DIR}/.env.dry_run" "${ENV_FILE}"
    chown "${BOT_USER}:${BOT_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "      .env created from .env.dry_run (DRY RUN mode – safe, no real orders)"
else
    echo "      .env already exists – not overwriting"
fi

# ── systemd service ───────────────────────────────────────────────────────────
echo "[8/8] Installing systemd service '${SERVICE_NAME}'…"
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
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}" || true   # don't abort if Docker pull fails on first boot

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Setup complete!  部署完成！"
echo " Finished at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo ""
echo " Bot directory : ${INSTALL_DIR}"
echo " Config file   : ${ENV_FILE}"
echo " Service       : ${SERVICE_NAME}"
echo " Full log      : ${LOG_FILE}"
echo ""
echo " ── Next steps (after SSH login) ──────────────────────────"
echo " 1. View setup log:"
echo "      tail -f ${LOG_FILE}"
echo ""
echo " 2. Edit credentials:"
echo "      nano ${ENV_FILE}"
echo ""
echo " 3. Switch to live trading (set TRADING_MODE=live in .env):"
echo "      systemctl restart ${SERVICE_NAME}"
echo ""
echo " 4. Monitor the bot:"
echo "      journalctl -u ${SERVICE_NAME} -f"
echo "      cd ${INSTALL_DIR} && docker compose logs -f"
echo ""
echo " 5. View trading data:"
echo "      cd ${INSTALL_DIR} && python view_trades.py"
echo "──────────────────────────────────────────────────────────"
