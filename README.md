# Polymarket BTC 5-Minute Multi-Window Trading Bot

Automated trading bot for Polymarket BTC Up/Down 5-minute markets. Uses real-time BTC momentum from Binance to build market bias and enters single-direction positions at precisely-timed windows before each market closes.

## Architecture

```
bot_runner.py              # Main loop: market detection → bias → window strategy → execution
lib/
  config.py                # All configuration (environment-variable driven)
  session_state.py         # Per-market session tracking (windows, open position)
  market_data.py           # BTC snapshot (Binance) + Polymarket orderbook snapshots
  market_bias.py           # UP / DOWN / NEUTRAL bias from BTC 5m & 15m momentum
  window_strategy.py       # Multi-window decision logic (window 0/1/2 + mid-review)
  execution.py             # Order execution layer (buy/sell, dry-run support)
  bot_state.py             # Global state persistence + crash recovery
  polymarket_client.py     # Polymarket CLOB API client
  utils.py                 # Shared utilities
tests/                     # Unit tests
deploy/                    # Deployment scripts and configuration
docs/                      # Additional documentation
legacy/                    # Previous hedge-based strategy (archived)
```

## Strategy Overview

### No Hedge — Single Direction

The bot takes a **single-direction position** aligned with BTC momentum. There is no dual-sided hedging.

### Decision Windows (seconds remaining before market close)

| Window | Seconds Remaining | Description |
|--------|------------------|-------------|
| Window 0 | 260–275s | Optional early momentum entry (disabled by default via `WINDOW0_ENABLED`) |
| Mid-review | 115–125s | Stop-out Window 0 positions if direction has flipped |
| Window 1 | 90–95s | **Primary entry point** |
| Window 2 | 30–35s | Stop-loss exit or high-confidence late entry |

### Market Bias

Bias is computed from real-time BTC price data (Binance API):
- **5-minute momentum** (default threshold: 0.15%)
- **15-minute momentum** (default threshold: 0.30%)
- Both timeframes must agree for a directional bias (configurable)
- Falls back to `NEUTRAL` on disagreement or missing data

### Hard Filters

- **Hard cap price**: Never buy if token price > `HARD_CAP_PRICE` (default 0.85)
- **Volatility safety**: Skip if recent 10s BTC price swing > `MAX_RECENT_VOLATILITY` (default 20%)
- **Spread check**: Skip if orderbook spread > `MAX_SPREAD`
- **Depth check**: Skip if combined bid+ask depth < `MIN_DEPTH`
- **Data delay check**: Skip if BTC data is stale (> 30s old)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env — at minimum set API_KEY

# Run in dry-run / observation mode (default — no real orders)
python bot_runner.py

# Run tests
pytest tests/ -v
```

## Configuration

All settings are driven by environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_ENABLED` | `false` | ⚠️ Must be `true` to place real orders |
| `DRY_RUN` | `true` | Simulate orders without submitting |
| `WINDOW0_ENABLED` | `false` | Enable early momentum window (experimental) |
| `HARD_CAP_PRICE` | `0.85` | Never buy above this price |
| `MIN_CONFIDENCE_W0` | `0.70` | Minimum price for Window 0 entry |
| `MIN_CONFIDENCE_W1` | `0.55` | Minimum price for Window 1 entry |
| `LATE_ENTRY_MIN_PRICE` | `0.65` | Minimum price for Window 2 late entry |
| `MAX_SPREAD` | `0.05` | Maximum allowable spread |
| `MIN_DEPTH` | `50.0` | Minimum combined orderbook depth (USDC) |
| `MOMENTUM_5M_THRESHOLD` | `0.0015` | 5m BTC move threshold for directional bias |
| `MOMENTUM_15M_THRESHOLD` | `0.003` | 15m BTC move threshold for trend |
| `MAX_RECENT_VOLATILITY` | `0.20` | Max 10s price swing before skipping |
| `BET_SIZE_USDC` | `3.0` | Size per trade in USDC |
| `DAILY_LOSS_LIMIT_USDC` | `20.0` | Daily loss circuit-breaker |
| `DAILY_TRADE_LIMIT` | `20` | Max trades per day |
| `CONSECUTIVE_LOSS_LIMIT` | `3` | Stop after N consecutive losses |
| `POLLING_INTERVAL` | `5000` | Main loop interval (milliseconds) |

## Risk Controls

- **Safety switch**: `TRADING_ENABLED=false` (default) — bot observes but never orders
- **Dry-run mode**: `DRY_RUN=true` (default) — orders are simulated and logged
- **Daily circuit-breaker**: halts trading when daily loss exceeds `DAILY_LOSS_LIMIT_USDC`
- **Consecutive loss protection**: stops after `CONSECUTIVE_LOSS_LIMIT` consecutive losses
- **Crash recovery**: `bot_state.json` written atomically; state restored on restart
- **UTC daily reset**: counters reset automatically at UTC midnight

## Docker Deployment

```bash
docker build -t polymarket-bot .
docker run -d --name polymarket-bot \
  --restart unless-stopped \
  --env-file .env \
  polymarket-bot
```

See [deploy/DEPLOYMENT_GUIDE.md](deploy/DEPLOYMENT_GUIDE.md) for full deployment instructions.

## Legacy Code

The previous hedge-based strategy has been moved to the [`legacy/`](legacy/) directory for reference.
