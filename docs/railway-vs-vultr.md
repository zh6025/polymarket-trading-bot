# Railway vs Vultr — Platform Comparison for Polymarket Bot

| Feature | Railway | Vultr (VPS) |
|---|---|---|
| Setup time | 5 min (GUI) | 15-30 min (SSH) |
| Min cost | ~$5/mo (usage-based) | $6/mo (1 vCPU, 1 GB) |
| Persistent storage | ❌ (ephemeral by default) | ✅ |
| SQLite support | ⚠️ (volume required) | ✅ |
| Auto-restart | ✅ | ✅ (systemd) |
| SSH access | ❌ | ✅ |
| Custom cron | ❌ | ✅ |
| Docker support | ✅ (native) | ✅ |
| Logs | ✅ (web UI) | ✅ (journalctl) |
| IPv4 | Shared | Dedicated |
| Best for | Quick demo/test | Production trading |

## Recommendation

Use **Railway** for rapid prototyping and CI/CD testing.  
Use **Vultr** (or Linode/DigitalOcean) for production with persistent SQLite state, crash recovery, and full cron/systemd control.

## Railway Quickstart

1. Fork this repo on GitHub
2. Connect to Railway → New Project → Deploy from GitHub
3. Add environment variables (`API_KEY`, `DRY_RUN=true`, `STRATEGY=imbalance`)
4. Set start command: `python bot_continuous.py`

## Vultr Quickstart

```bash
# On a fresh Ubuntu 22.04 VPS:
export REPO_URL=https://github.com/zh6025/polymarket-trading-bot.git
curl -fsSL https://raw.githubusercontent.com/zh6025/polymarket-trading-bot/main/deploy/setup-linode.sh | bash
# Then follow deploy/DEPLOYMENT_GUIDE.md
```
