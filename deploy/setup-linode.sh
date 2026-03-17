#!/bin/bash
# =============================================================================
# Polymarket Trading Bot - Linode Server Initialization Script
# =============================================================================
# This script sets up a fresh Linode Ubuntu server with all required
# dependencies for running the Polymarket Trading Bot.
#
# Usage: sudo ./setup-linode.sh
# =============================================================================

set -euo pipefail

# ---- Colors for output ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_section() { echo -e "\n${BLUE}==== $* ====${NC}"; }

# ---- Require root ----
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Use: sudo ./setup-linode.sh"
    exit 1
fi

BOT_USER="${BOT_USER:-ubuntu}"
BOT_DIR="${BOT_DIR:-/opt/polymarket-trading-bot}"

log_section "Polymarket Bot - Linode Server Setup"
log_info "Bot user  : $BOT_USER"
log_info "Bot dir   : $BOT_DIR"
log_info "Date/Time : $(date)"

# =============================================================================
# 1. System update and base packages
# =============================================================================
log_section "System Update"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl \
    wget \
    git \
    htop \
    unzip \
    vim \
    nano \
    net-tools \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    apt-transport-https \
    logrotate \
    fail2ban \
    ufw
log_info "Base packages installed."

# =============================================================================
# 2. Set timezone
# =============================================================================
log_section "Timezone Configuration"
timedatectl set-timezone UTC
log_info "Timezone set to UTC."

# =============================================================================
# 3. Docker installation
# =============================================================================
log_section "Docker Installation"
if command -v docker &>/dev/null; then
    log_warn "Docker already installed: $(docker --version)"
else
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    log_info "Docker installed: $(docker --version)"
fi

# =============================================================================
# 4. Docker Compose (standalone binary, for compatibility)
# =============================================================================
log_section "Docker Compose Installation"
if command -v docker-compose &>/dev/null; then
    log_warn "docker-compose already installed: $(docker-compose --version)"
else
    COMPOSE_VERSION=$(curl -fsSL https://api.github.com/repos/docker/compose/releases/latest \
        | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
    curl -fsSL \
        "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    log_info "Docker Compose installed: $(docker-compose --version)"
fi

# =============================================================================
# 5. Create bot user and directories
# =============================================================================
log_section "User and Directory Setup"
if ! id "$BOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$BOT_USER"
    log_info "Created user: $BOT_USER"
else
    log_warn "User $BOT_USER already exists."
fi

usermod -aG docker "$BOT_USER"
log_info "Added $BOT_USER to docker group."

mkdir -p "$BOT_DIR"
mkdir -p "$BOT_DIR/logs"
mkdir -p "$BOT_DIR/backups"
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"
log_info "Directories created under $BOT_DIR"

# =============================================================================
# 6. Firewall (UFW)
# =============================================================================
log_section "Firewall Configuration (UFW)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment 'SSH'
ufw allow 8080/tcp comment 'Adminer/Dashboard (optional)'
ufw --force enable
ufw status verbose
log_info "UFW configured."

# =============================================================================
# 7. Fail2ban
# =============================================================================
log_section "Fail2ban Configuration"
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
EOF
systemctl enable fail2ban
systemctl restart fail2ban
log_info "Fail2ban configured and started."

# =============================================================================
# 8. Log rotation for bot logs
# =============================================================================
log_section "Log Rotation"
cat > /etc/logrotate.d/polymarket-bot <<EOF
$BOT_DIR/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 $BOT_USER $BOT_USER
    sharedscripts
    postrotate
        docker kill --signal=USR1 polymarket-bot 2>/dev/null || true
    endscript
}
EOF
log_info "Log rotation configured."

# =============================================================================
# 9. Swap (1 GB) — useful for small Linode instances
# =============================================================================
log_section "Swap Configuration"
if swapon --show | grep -q '/swapfile'; then
    log_warn "Swap already enabled."
else
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    log_info "1 GB swap created."
fi

# =============================================================================
# 10. SSH hardening
# =============================================================================
log_section "SSH Hardening"
sed -i 's/^#\?PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd
log_info "SSH hardened."

# =============================================================================
# Done
# =============================================================================
log_section "Setup Complete"
log_info "Server initialization finished successfully."
log_info "Next step: run  deploy/deploy.sh  to deploy the bot."
log_warn "If you changed SSH settings, make sure your key-based login works before closing this session."
