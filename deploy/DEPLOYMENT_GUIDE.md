# Polymarket Trading Bot — Deployment Guide

## Quick Start (Docker)

```bash
cp .env.example .env
# Edit .env: set API_KEY, TRADING_ENABLED=true, DRY_RUN=false
docker-compose up -d bot
docker-compose logs -f bot
```

## Linode One-Click Setup

```bash
export REPO_URL=https://github.com/zh6025/polymarket-trading-bot.git
curl -fsSL https://raw.githubusercontent.com/zh6025/polymarket-trading-bot/main/deploy/setup-linode.sh | bash
```

## Deploy / Update

```bash
cd /opt/polymarket-bot
./deploy/deploy.sh
```

## Production Compose

```bash
cd deploy/
docker-compose -f docker-compose.prod.yml up -d
```

## Systemd Service

```bash
cp deploy/systemd/polymarket-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot
systemctl start polymarket-bot
journalctl -u polymarket-bot -f
```

## Health Check (Cron)

```cron
*/5 * * * * /opt/polymarket-bot/deploy/health-check.sh >> /var/log/polymarket-health.log 2>&1
```

## Backup (Cron)

```cron
0 2 * * * /opt/polymarket-bot/deploy/backup.sh >> /var/log/polymarket-backup.log 2>&1
```

## Strategy Selection

Set `STRATEGY` in `.env`:

| Value | Description |
|---|---|
| `imbalance` | Late-entry single-side (default) |
| `directional` | EMA+ATR BTC trend following |
| `momentum_hedge` | 70% trigger + Kelly hedge |

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | — | Polymarket CLOB API key |
| `DRY_RUN` | `true` | Simulate orders only |
| `TRADING_ENABLED` | `false` | Enable real order placement |
| `STRATEGY` | `imbalance` | Strategy: imbalance/directional/momentum_hedge |
| `DAILY_LOSS_LIMIT_USDC` | `20` | Stop trading after this daily loss |
| `DAILY_TRADE_LIMIT` | `20` | Max trades per day |
| `CONSECUTIVE_LOSS_LIMIT` | `3` | Max consecutive losses |
| `MAIN_BET_SIZE_USDC` | `3.0` | Notional per main bet |
| `MAIN_MAX_PRICE` | `0.66` | Max entry price for main leg |
| `DOMINANCE_THRESHOLD` | `0.68` | Imbalance trigger threshold |
| `TRIGGER_THRESHOLD` | `0.70` | Momentum hedge trigger |
| `ENABLE_HEDGE` | `false` | Enable hedge leg |
