# Live Trading Preparation Checklist

A step-by-step checklist for transitioning from dry-run to live trading.

---

## Pre-Launch Verification

### 1. Strategy Validation (Dry Run)

- [ ] Run bot with `DRY_RUN=true` for at least 24 hours
- [ ] Verify window entries fire at correct time boundaries
- [ ] Confirm bias computation matches manual BTC price observation
- [ ] Check that circuit breakers trigger correctly (simulate losses)
- [ ] Review dry-run logs for unexpected SKIPs or errors

### 2. API Configuration

- [ ] Obtain Polymarket CLOB API credentials (API_KEY, API_SECRET, API_PASSPHRASE)
- [ ] Verify credentials work: bot can fetch markets and orderbooks
- [ ] Confirm Binance public endpoints are accessible from deployment server
- [ ] Test clock synchronization (server time vs Polymarket server time)

### 3. Risk Parameters

Review and adjust these before going live:

| Parameter | Default | Recommended First Run | Notes |
|-----------|---------|----------------------|-------|
| `BET_SIZE_USDC` | 3.0 | 1.0 – 2.0 | Start small |
| `DAILY_LOSS_LIMIT_USDC` | 20.0 | 5.0 – 10.0 | Tighten for first week |
| `DAILY_TRADE_LIMIT` | 20 | 10 | Lower to observe behavior |
| `CONSECUTIVE_LOSS_LIMIT` | 3 | 2 | Aggressive stop at first |
| `WINDOW0_ENABLED` | false | false | Keep disabled initially |

### 4. Deployment Environment

- [ ] Server has stable internet connection with low latency to APIs
- [ ] Python 3.10+ installed with all dependencies (`pip install -r requirements.txt`)
- [ ] `.env` file configured (copy from `.env.example`)
- [ ] `bot_state.json` does not exist (fresh start) or is from a clean state
- [ ] Process manager configured (systemd / Docker / supervisor)
- [ ] Log rotation configured for long-running operation

---

## Go-Live Sequence

### Step 1: Observation Mode

```bash
# .env settings:
TRADING_ENABLED=false
DRY_RUN=true
```

Run for 24-48 hours. Review logs for:
- Correct market detection and session resets
- Bias computation quality
- Window trigger timing
- Simulated order placement

### Step 2: Dry Run with Trading Enabled

```bash
TRADING_ENABLED=true
DRY_RUN=true
```

Same as above, but `execution.py` will process the full order path (stopping short of API call). Verify:
- Order parameters look correct (token_id, side, price, size)
- PnL tracking works correctly

### Step 3: Live with Minimum Size

```bash
TRADING_ENABLED=true
DRY_RUN=false
BET_SIZE_USDC=1.0
DAILY_LOSS_LIMIT_USDC=5.0
DAILY_TRADE_LIMIT=5
```

Run for 1-3 days. Monitor:
- [ ] Orders execute successfully on Polymarket
- [ ] Fills match expected prices
- [ ] PnL tracking matches actual account balance
- [ ] Circuit breakers work in production

### Step 4: Scale Up

Gradually increase parameters toward defaults:
```bash
BET_SIZE_USDC=3.0
DAILY_LOSS_LIMIT_USDC=20.0
DAILY_TRADE_LIMIT=20
```

---

## Monitoring in Production

### Key Metrics to Track

- **Win rate**: Target > 55% for profitability at these spreads
- **Average PnL per trade**: Should be positive after spread costs
- **Daily PnL**: Watch for trending losses → reduce size or pause
- **Circuit breaker triggers**: Frequent triggers = strategy needs adjustment

### Log Monitoring

```bash
# Follow live logs
tail -f bot.log | grep -E "(ENTER|STOP_LOSS|SKIP|ERROR|circuit_breaker)"

# Check daily summary
grep "daily_reset" bot.log
```

### Emergency Stop

To immediately stop trading without killing the process:
1. Set `TRADING_ENABLED=false` in `.env`
2. Bot will enter observation mode on next cycle

To kill:
```bash
# If running via systemd:
sudo systemctl stop polymarket-bot

# If running via Docker:
docker compose down
```

---

## Rollback Plan

If live trading shows unexpected behavior:

1. **Immediate**: Set `TRADING_ENABLED=false`
2. **Review**: Check `bot_state.json` for position state
3. **Manual close**: If positions are open, close them manually on Polymarket
4. **Investigate**: Review logs, identify root cause
5. **Fix and retest**: Return to dry-run mode before re-enabling
