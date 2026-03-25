# Polymarket Trading Bot

Automated trading bot for Polymarket BTC 5-minute binary markets using a **momentum hedge strategy** with Kelly-optimal bet sizing.

---

## Architecture

```
bot_runner.py          # Production entry point (live / dry-run)
bot_simulate.py        # Simulation entry point (market data, no orders)
bot_continuous.py      # Legacy continuous loop
web_dashboard.py       # Flask monitoring dashboard (port 5000)

lib/
  config.py            # All configuration via environment variables
  polymarket_client.py # CLOB API client (market data + orderbook)
  decision.py          # Momentum hedge strategy + Kelly sizing
  bot_state.py         # State persistence & daily risk tracking
  trading_engine.py    # Order placement (dry-run / live)
  data_persistence.py  # SQLite trade history
  monitoring.py        # Dashboard metrics
  risk_manager.py      # Additional risk checks
  utils.py             # HTTP client + logging helpers
```

---

## Strategy

The bot watches BTC 5-minute binary markets on Polymarket.

1. **Momentum trigger** — when one side (YES or NO) reaches >= 70% probability, enter on that side.
2. **Kelly sizing** — bet size is calculated using the Kelly criterion with a configurable edge assumption (default 5% over market).
3. **Hedge** — a smaller counter-bet (default 30% of main size) is placed on the opposite side to limit downside.
4. **Risk controls** — hard limits on daily loss (USDC), consecutive losses, and daily trade count; state is persisted to JSON for crash recovery.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env -- fill in your API key and private key
```

### 3. Dry-run (safe, no real orders)

```bash
python bot_runner.py
```

### 4. Simulation (market data only)

```bash
python bot_simulate.py
```

### 5. Live trading

Only after validating dry-run behaviour:

```bash
# In .env:
DRY_RUN=false
TRADING_ENABLED=true
```

```bash
python bot_runner.py
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `HOST` | `https://clob.polymarket.com` | CLOB API host |
| `CHAIN_ID` | `137` | Polygon chain ID |
| `PRIVATE_KEY` | *(required for live)* | Wallet private key |
| `PROXY_ADDRESS` | *(optional)* | Polymarket proxy contract address |
| `API_KEY` | *(optional)* | Polymarket API key |
| `DRY_RUN` | `true` | If true, no real orders are placed |
| `TRADING_ENABLED` | `false` | Must be `true` to allow live orders |
| `STATE_FILE_PATH` | `bot_state.json` | Path to persist bot state |
| `MOMENTUM_THRESHOLD` | `0.70` | Minimum price to trigger entry |
| `EDGE_FACTOR` | `0.05` | Assumed probability edge for Kelly |
| `KELLY_FRACTION_CAP` | `0.25` | Max Kelly fraction (25% of bankroll) |
| `HEDGE_RATIO` | `0.30` | Hedge size as fraction of main bet |
| `ENABLE_HEDGE` | `true` | Whether to place hedge orders |
| `BANKROLL` | `100.0` | Available capital for Kelly sizing (USDC) |
| `MIN_ORDER_SIZE` | `3.0` | Minimum order size (USDC) |
| `MAX_ORDER_SIZE` | `50.0` | Maximum order size (USDC) |
| `DAILY_LOSS_LIMIT_USDC` | `20` | Daily loss hard stop (USDC) |
| `DAILY_TRADE_LIMIT` | `20` | Max trades per day |
| `CONSECUTIVE_LOSS_LIMIT` | `3` | Max consecutive losses before halt |
| `POLLING_INTERVAL` | `10` | Seconds between market checks |

---

## Docker Deployment

```bash
# Copy and edit config
cp .env.example .env

# Run bot only
docker-compose up bot

# Run with dashboard
docker-compose --profile dashboard up

# Run simulation
docker-compose --profile simulate up
```

Dashboard is available at http://localhost:5000.

---

## Risk Controls

- **Daily loss limit** -- bot halts when daily PnL < -`DAILY_LOSS_LIMIT_USDC`.
- **Consecutive losses** -- bot halts after `CONSECUTIVE_LOSS_LIMIT` back-to-back losses.
- **Daily trade cap** -- no more than `DAILY_TRADE_LIMIT` trades per calendar day.
- **Crash recovery** -- state is persisted to `bot_state.json`; the bot resumes correctly after a restart.
- **Dry-run default** -- `DRY_RUN=true` by default; real orders require explicitly setting `TRADING_ENABLED=true`.
