# Polymarket Trading Bot

A Python-based automated trading bot for Polymarket BTC Up/Down 5-minute prediction markets. Uses Polymarket's CLOB API for order placement and Gamma API for market discovery.

## Architecture

```
polymarket-trading-bot/
├── bot_runner.py          # Single-cycle trading entry point
├── bot_continuous.py      # Continuous loop trading entry point
├── bot_simulate.py        # Simulation / dry-run mode
├── web_dashboard.py       # Web dashboard (Flask, port 5000)
├── lib/
│   ├── config.py          # Configuration loader (env vars → BotConfig)
│   ├── polymarket_client.py  # Polymarket CLOB + Gamma API client
│   ├── risk.py            # Full-featured risk manager (bot_runner.py)
│   ├── risk_manager.py    # Lightweight risk manager (bot_continuous.py)
│   ├── strategy.py        # ProductionDecisionStrategy
│   ├── trading_engine.py  # Order book signal engine
│   ├── bot_state.py       # JSON state persistence
│   ├── data_persistence.py  # SQLite trade/position records
│   ├── monitoring.py      # Dashboard data aggregation
│   └── utils.py           # Logging helpers, APIClient
├── scripts/
│   ├── plan-grid-dryrun.js   # Grid strategy dry-run planner
│   └── watch-grid-dryrun.js  # Grid strategy watcher
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Installation

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

| Variable | Default | Description |
|---|---|---|
| `PK` | — | Polymarket private key (hex, no 0x prefix) |
| `PROXY_ADDRESS` | — | Polymarket proxy/funder wallet address |
| `DRY_RUN` | `true` | When `true`, no real orders are placed |
| `TRADING_ENABLED` | `false` | Master trading switch |
| `MIN_ORDER_SIZE` | `5.0` | Minimum order size in USDC |
| `MAX_POSITION_SIZE` | `50.0` | Max position size per token |
| `MAX_DAILY_LOSS` | `30.0` | Daily loss circuit breaker (USDC) |
| `MAX_TRADES_PER_DAY` | `20` | Daily trade count limit |
| `CHAIN_ID` | `137` | Polygon chain ID |
| `POLYMARKET_HOST` | `https://clob.polymarket.com` | CLOB API endpoint |
| `GAMMA_HOST` | `https://gamma-api.polymarket.com` | Gamma API endpoint |

See `.env.example` for the full list of options.

## Running the Bot

### Dry-run (single cycle, no real orders)

```bash
DRY_RUN=true python bot_runner.py
```

### Simulation mode (continuous loop, no real orders)

```bash
python bot_simulate.py
```

### Continuous production mode

```bash
DRY_RUN=false TRADING_ENABLED=true python bot_continuous.py
```

### Web Dashboard

```bash
python web_dashboard.py
# Open http://localhost:5000
```

## Docker Deployment

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env

# Start the main bot
docker compose up bot

# Start simulation mode
docker compose --profile simulate up bot-simulate

# Start with dashboard
docker compose --profile dashboard up dashboard
```

See [DEPLOY.md](DEPLOY.md) for full deployment instructions.

## Risk Management

The bot implements multiple risk controls:

- **Daily loss limit** — stops trading if cumulative daily P&L drops below threshold
- **Position size limit** — caps exposure per token
- **Daily trade limit** — prevents overtrading
- **Cooldown period** — enforces minimum time between trades
- **Consecutive loss circuit breaker** — halts after N consecutive losing trades
- **Time-to-expiry filters** — skips markets too close to settlement
- **Spread and depth filters** — only trades liquid markets

## ⚠️ Risk Disclaimer

This software is provided for educational and research purposes. Prediction market trading involves significant financial risk. Always start with `DRY_RUN=true` and small position sizes. Never risk more than you can afford to lose.
