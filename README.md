# Polymarket BTC 5-Minute Trading Bot

An automated trading bot for Polymarket's BTC Up/Down 5-minute binary options markets, written in Python.

## Overview

The bot monitors Polymarket's BTC 5-minute binary prediction markets and uses order-book imbalance detection combined with a Kelly-optimal hedge strategy to make trading decisions.

### Architecture

| File | Role |
|------|------|
| `bot_runner.py` | **Single-shot runner** — designed to be called by a cron job or scheduler once per tick. Loads state, evaluates the market, places orders if warranted, and exits. |
| `bot_continuous.py` | **Continuous loop** — runs forever, refreshing the market every 5 minutes and polling the order book every few seconds. |
| `web_dashboard.py` | Flask monitoring dashboard for viewing trade history and PnL. |
| `lib/` | Shared library modules (config, strategy, risk, persistence, etc.). |

### Library Modules

| Module | Description |
|--------|-------------|
| `lib/config.py` | `load_config()` — reads all settings from environment variables. |
| `lib/bot_state.py` | JSON-backed state (open positions, daily PnL counters). |
| `lib/strategy.py` | `ProductionDecisionStrategy` — entry signal with Kelly-optimal hedge sizing. |
| `lib/risk.py` | `RiskManager` — per-run risk gates (loss limit, cooldown) for `bot_runner.py`. |
| `lib/risk_manager.py` | `RiskManager` — stateful risk gates for `bot_continuous.py`. |
| `lib/trading_engine.py` | Order-book analysis (`evaluate`) and legacy order placement. |
| `lib/polymarket_client.py` | CLOB + Gamma API client (market discovery, order book, order placement). |
| `lib/data_persistence.py` | SQLite persistence for trades and open positions. |
| `lib/monitoring.py` | Dashboard data aggregation. |
| `lib/utils.py` | HTTP client, logging helpers, `round_to_tick`. |

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API key, private key, proxy address, etc.
```

Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PRIVATE_KEY` | Ethereum wallet private key | — |
| `PROXY_ADDRESS` | Polymarket proxy wallet address | — |
| `API_KEY` | Polymarket CLOB API key | — |
| `DRY_RUN` | `true` = simulate only, no real orders | `true` |
| `MAX_DAILY_LOSS` | Stop trading when daily loss exceeds this (USDC) | `100` |
| `MIN_ORDER_SIZE` | Minimum order size in USDC | `5` |

See `.env.example` for the full list of configuration options.

## Running

### Dry-run mode (safe, no real orders)

```bash
# Single-shot runner
DRY_RUN=true python bot_runner.py

# Continuous loop
DRY_RUN=true python bot_continuous.py
```

### Live trading

```bash
# Make sure .env has DRY_RUN=false and real credentials
python bot_runner.py
```

### Web dashboard

```bash
python web_dashboard.py
# Open http://localhost:8501
```

## Docker Deployment

```bash
# Build and start the single-shot bot
docker compose up -d bot

# Or run the continuous loop
docker compose --profile continuous up -d bot-continuous

# Optional: web dashboard
docker compose --profile dashboard up -d dashboard
```

## Risk Management

The bot has multiple layers of risk control:

- **Daily loss limit** — stops all trading once realised PnL drops below `MAX_DAILY_LOSS`.
- **Consecutive loss limit** — pauses after `CONSECUTIVE_LOSS_LIMIT` back-to-back losses.
- **Daily trade cap** — limits entries to `MAX_TRADES_PER_DAY` per calendar day.
- **Position size limit** — never allocates more than `MAX_POSITION_SIZE` USDC per direction.
- **Cooldown** — enforces a `COOLDOWN_SECONDS` pause between trades on the same market.
- **Timing guard** — blocks new entries within `HARD_STOP_NEW_ENTRY_SEC` of market expiry.
- **Price range filter** — only trades when the main-leg price is in `[MIN_MAIN_PRICE, MAX_MAIN_PRICE]`.
- **Depth guard** — requires minimum bid-side liquidity before entering.
- **One position per market** — prevents doubling into the same market window.

## File Structure

```
.
├── bot_runner.py          # Single-shot production runner
├── bot_continuous.py      # Continuous market-making loop
├── web_dashboard.py       # Monitoring dashboard
├── lib/
│   ├── config.py          # Environment config loader
│   ├── bot_state.py       # Persistent bot state
│   ├── strategy.py        # ProductionDecisionStrategy + GridStrategy
│   ├── risk.py            # Risk gatekeeper (bot_runner)
│   ├── risk_manager.py    # Risk manager (bot_continuous)
│   ├── trading_engine.py  # Order-book evaluation + execution
│   ├── polymarket_client.py # API client
│   ├── data_persistence.py  # SQLite persistence
│   ├── monitoring.py      # Dashboard metrics
│   └── utils.py           # HTTP client, logging helpers
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── DEPLOY.md
```

## License

MIT
