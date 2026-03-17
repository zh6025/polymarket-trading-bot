# Polymarket Trading Bot — Linode Deployment Guide

This guide walks you through deploying the Polymarket Trading Bot on a fresh
Linode (Ubuntu 22.04 LTS) server using Docker Compose.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create a Linode Instance](#2-create-a-linode-instance)
3. [Find Your Linode IP Address](#3-find-your-linode-ip-address)
4. [Initialize the Server](#4-initialize-the-server)
5. [Configure the Environment](#5-configure-the-environment)
6. [Deploy the Bot](#6-deploy-the-bot)
7. [Enable Systemd Auto-start](#7-enable-systemd-auto-start)
8. [Monitoring and Logs](#8-monitoring-and-logs)
9. [Backup and Restore](#9-backup-and-restore)
10. [Updating the Bot](#10-updating-the-bot)
11. [Troubleshooting](#11-troubleshooting)
12. [Security Checklist](#12-security-checklist)

---

## 1. Prerequisites

| Requirement | Detail |
|-------------|--------|
| Linode account | <https://cloud.linode.com> |
| Ubuntu 22.04 LTS | Recommended OS image |
| RAM | Minimum 1 GB (2 GB recommended) |
| Disk | 25 GB SSD or more |
| Polymarket API key | Obtain from your Polymarket account settings |
| SSH key pair | Generated locally — **never use password auth in production** |

---

## 2. Create a Linode Instance

1. Log in to [Linode Cloud Manager](https://cloud.linode.com).
2. Click **Create → Linode**.
3. Select:
   - **Distribution**: Ubuntu 22.04 LTS
   - **Region**: closest to your location
   - **Plan**: Shared CPU — Nanode 1 GB (or Linode 2 GB for better performance)
4. Under **Authentication**, paste your **SSH public key**.
5. Click **Create Linode** and wait for the instance to boot.
6. Note the **IPv4 address** shown in the dashboard.

---

## 3. Find Your Linode IP Address

You need the server's public IPv4 address to SSH in and to configure any
external monitoring tools.  There are three ways to obtain it.

### Method 1 — Linode Cloud Manager (web UI)

1. Open [https://cloud.linode.com](https://cloud.linode.com) and log in.
2. Click **Linodes** in the left sidebar.
3. Find your instance in the list.  The **IP Address** column shows the public
   IPv4 address directly on the list page.

   ```
   Linodes
   ┌────────────────────┬───────────────┬──────────────┐
   │ Label              │ Status        │ IP Address   │
   ├────────────────────┼───────────────┼──────────────┤
   │ polymarket-bot     │ ● Running     │ 45.79.XX.XX  │
   └────────────────────┴───────────────┴──────────────┘
   ```

4. Click the instance name to open its **Summary** page.  Under the
   **IP Addresses** section you will see:
   - **IPv4** — public address (e.g. `45.79.XX.XX`)
   - **IPv6** — public IPv6 address (optional)
   - **Private IP** — internal Linode network address (not routable from the
     internet)

### Method 2 — Linode CLI

If you have the [Linode CLI](https://www.linode.com/docs/products/tools/cli/)
installed on your local machine:

```bash
# Install (if not already installed)
pip install linode-cli

# Log in with your Linode personal access token
linode-cli configure

# List all Linodes and their IPs
linode-cli linodes list
```

Example output:

```
┌──────────┬─────────────────┬────────────┬──────────────┐
│ id       │ label           │ status     │ ipv4         │
├──────────┼─────────────────┼────────────┼──────────────┤
│ 12345678 │ polymarket-bot  │ running    │ 45.79.XX.XX  │
└──────────┴─────────────────┴────────────┴──────────────┘
```

To show a specific Linode's full network details:

```bash
linode-cli linodes view 12345678
```

### Method 3 — From Inside the Server

Once you have connected to your Linode (even via the **Lish console** in the
Cloud Manager), run any of these commands to confirm the public IP:

```bash
# Show all network interfaces and their addresses
ip addr show eth0

# Query a public metadata endpoint (returns only the IP as plain text)
curl -s https://api.ipify.org

# Alternative metadata endpoints
curl -s https://ifconfig.me
curl -s https://icanhazip.com
```

> **Linode Metadata Service** — Linode also provides an internal metadata API.
> From within a running Linode you can retrieve instance information
> (including IP) via:
>
> ```bash
> curl -s http://169.254.169.254/v1/instance
> ```

### Using the IP Address

Once you have the IP, substitute it wherever `<your-linode-ip>` appears in
this guide.  Example:

```bash
# SSH into the server
ssh root@45.79.XX.XX

# Or, if using a non-root user after setup-linode.sh
ssh ubuntu@45.79.XX.XX
```

---

## 4. Initialize the Server

Connect to the server and run the one-time setup script.

```bash
# Connect via SSH
ssh root@<your-linode-ip>

# Clone the repository
cd /opt
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot

# Make scripts executable
chmod +x deploy/*.sh

# Run initialization (takes ~5 minutes)
sudo bash deploy/setup-linode.sh
```

The `setup-linode.sh` script will:

- Update and upgrade all system packages
- Install Docker CE and Docker Compose
- Create an `ubuntu` user and add it to the `docker` group
- Configure UFW firewall (SSH on 22, optional dashboard on 8080)
- Enable Fail2ban to block brute-force SSH attempts
- Create a 1 GB swap file (useful for small instances)
- Set up log rotation for bot logs

---

## 5. Configure the Environment

```bash
# Copy the production template to the project root
cp deploy/.env.production .env

# Restrict permissions (important — this file contains secrets)
chmod 600 .env

# Edit and fill in your real API credentials
nano .env
```

Key variables to set:

```dotenv
# Your Polymarket API credentials (required for live trading)
API_KEY=<your-polymarket-api-key>
API_SECRET=<your-polymarket-api-secret>
API_PASSPHRASE=<your-polymarket-api-passphrase>

# Set to false only when you are ready to trade with real money
DRY_RUN=false

# Risk limits (adjust to your risk appetite)
DAILY_LOSS_LIMIT=100
MAX_POSITION_SIZE=500
```

> **Tip**: Leave `DRY_RUN=true` for your first deployment to verify everything
> works correctly before going live.

---

## 6. Deploy the Bot

```bash
cd /opt/polymarket-trading-bot

# Full deployment (build image, start containers)
bash deploy/deploy.sh
```

To update without pulling latest code (e.g., after manual edits):

```bash
bash deploy/deploy.sh --no-pull
```

To skip the pre-deploy backup:

```bash
bash deploy/deploy.sh --skip-backup
```

Verify the container is running:

```bash
docker ps
docker logs -f polymarket-bot
```

---

## 7. Enable Systemd Auto-start

The bot will automatically restart after a server reboot.

```bash
# Copy the service unit file
sudo cp deploy/systemd/polymarket-bot.service /etc/systemd/system/

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot

# Start immediately
sudo systemctl start polymarket-bot

# Check status
sudo systemctl status polymarket-bot
```

Useful systemd commands:

| Action | Command |
|--------|---------|
| Start  | `sudo systemctl start polymarket-bot` |
| Stop   | `sudo systemctl stop polymarket-bot` |
| Restart | `sudo systemctl restart polymarket-bot` |
| Status  | `sudo systemctl status polymarket-bot` |
| Live logs | `journalctl -u polymarket-bot -f` |

---

## 8. Monitoring and Logs

### Real-time container logs

```bash
docker logs -f polymarket-bot
```

### Health check (manual)

```bash
bash deploy/health-check.sh
```

### Automated health check (every 5 minutes via cron)

```bash
crontab -e
```

Add the following line:

```cron
*/5 * * * * /opt/polymarket-trading-bot/deploy/health-check.sh >> /opt/polymarket-trading-bot/logs/health-check.log 2>&1
```

### Resource usage

```bash
docker stats polymarket-bot   # live CPU/memory
docker inspect polymarket-bot # detailed metadata
```

### Alert configuration

Edit `deploy/health-check.sh` and set:

```bash
ALERT_METHOD=email
ALERT_EMAIL=you@example.com
```

Make sure `mailutils` is installed (`apt install mailutils`) and configured.

---

## 9. Backup and Restore

### Manual backup

```bash
bash deploy/backup.sh
```

Backups are saved to `/opt/polymarket-trading-bot/backups/`.

### Automated daily backup (2 AM)

```bash
crontab -e
```

Add:

```cron
0 2 * * * /opt/polymarket-trading-bot/deploy/backup.sh >> /opt/polymarket-trading-bot/logs/backup.log 2>&1
```

### Restore from backup

```bash
# List available backups
ls -lh /opt/polymarket-trading-bot/backups/

# Extract a specific backup
BACKUP=backup_20240101_020000.tar.gz
tar -xzf /opt/polymarket-trading-bot/backups/$BACKUP \
    -C /tmp/restore/

# Restore database
docker cp /tmp/restore/*/bot_data.db polymarket-bot:/app/bot_data.db

# Restart the bot
sudo systemctl restart polymarket-bot
```

---

## 10. Updating the Bot

```bash
cd /opt/polymarket-trading-bot

# Pull latest code
git pull origin main

# Rebuild and redeploy (automatically creates a pre-deploy backup)
bash deploy/deploy.sh
```

---

## 11. Troubleshooting

### Container exits immediately

```bash
# View the last 100 log lines
docker logs --tail=100 polymarket-bot

# Common causes:
# - Missing or invalid API_KEY in .env
# - Python import error (dependency missing in Dockerfile)
# - DRY_RUN=false with invalid credentials
```

### API connection errors

```bash
# Check network connectivity
curl -I https://clob.polymarket.com/markets

# Verify API key is set correctly
grep API_KEY /opt/polymarket-trading-bot/.env
```

### High memory / OOM kills

```bash
# Check memory limits in docker-compose.prod.yml
# Increase the limits.memory value, then redeploy:
bash deploy/deploy.sh --no-pull
```

### Disk full

```bash
# Check disk usage
df -h
du -sh /opt/polymarket-trading-bot/logs/*

# Clean up Docker resources
docker system prune -f

# Reduce log retention in /etc/logrotate.d/polymarket-bot
```

### Firewall blocking connections

```bash
sudo ufw status verbose
# To allow a new port:
sudo ufw allow <port>/tcp
```

### Fail2ban blocking your own IP

```bash
sudo fail2ban-client status sshd
sudo fail2ban-client set sshd unbanip <your-ip>
```

---

## 12. Security Checklist

- [ ] `.env` file has permissions `600` (`chmod 600 .env`)
- [ ] SSH password authentication is disabled (key-only login)
- [ ] UFW firewall is active with only required ports open
- [ ] Fail2ban is enabled and running
- [ ] `DRY_RUN=true` tested before enabling live trading
- [ ] Daily automated backups are scheduled in cron
- [ ] Health check cron job is configured and alerting
- [ ] API keys are stored only in `.env` (never committed to Git)
- [ ] Server OS packages are kept up to date (`apt upgrade`)
- [ ] Docker images are rebuilt periodically to pick up security patches

---

## File Structure

```
polymarket-trading-bot/
├── deploy/
│   ├── setup-linode.sh          # One-time server initialization
│   ├── deploy.sh                # Build and start the bot
│   ├── health-check.sh          # Container + API health checks
│   ├── backup.sh                # Database and config backup
│   ├── .env.production          # Production .env template
│   ├── docker-compose.prod.yml  # Production Docker Compose
│   ├── DEPLOYMENT_GUIDE.md      # This file
│   └── systemd/
│       └── polymarket-bot.service  # Systemd unit file
├── Dockerfile
├── docker-compose.yml           # Development compose
├── requirements.txt
└── ...
```
