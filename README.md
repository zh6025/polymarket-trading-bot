# Polymarket BTC Up/Down 5-Minute Trading Bot

An automated, production-ready trading bot that continuously discovers and
trades the recurring **"BTC Up or Down – 5 Minutes"** markets on
[Polymarket](https://polymarket.com) (CLOB), following a configurable
momentum-plus-orderbook strategy with strict risk controls.

> ⚠️ **Risk warning**: This bot places real orders with real money. Prediction
> markets are highly speculative. Only trade capital you can afford to lose.
> You are solely responsible for understanding the strategy, verifying the
> code, and complying with the laws of your jurisdiction.

---

## Table of Contents

1. [Overview](#overview)
2. [Setup](#setup)
3. [Configuration Variables](#configuration-variables)
4. [Running with Docker](#running-with-docker)
5. [How the Strategy Works](#how-the-strategy-works)
6. [Daily Loss Limit](#daily-loss-limit)
7. [DRY RUN Mode](#dry-run-mode)
8. [Project Structure](#project-structure)
9. [Running Tests](#running-tests)

---

## Overview

Each **BTC Up or Down – 5 Minutes** market on Polymarket runs for exactly
5 minutes and resolves based on whether the Chainlink BTC/USD price at
market end is higher or lower than at market start.

The bot:

- **Auto-discovers** the currently active 5-minute BTC market and rolls to
  the next one when it expires.
- **Observes** the order book until the UP and DOWN ask prices diverge by at
  least 10% (configurable).
- **Checks the BTC trend** using 5-minute and 15-minute price returns from
  the Binance feed to decide direction.
- **Places a $1 USDC buy** in the trending direction.
- **Opportunistically buys** a second position if either side's ask drops
  below $0.20, and takes profit if that position rises above $0.40.
- **Manages exits**: sells on trend reversal, takes profit on opportunity
  position, and flattens or holds in the final 60 seconds.
- **Enforces risk limits**: $1 per trade, $10 daily max loss, max 2 entries
  per market, stops trading on repeated API failures.

---

## Setup

### Prerequisites

- Docker and Docker Compose installed on your VPS
- A Polymarket account with:
  - An Ethereum private key (`PK`) controlling your Polymarket wallet
  - CLOB API credentials (key, secret, passphrase) from Polymarket Settings
- (Optional) A Polygon RPC URL from [Alchemy](https://alchemy.com) or
  [Infura](https://infura.io) for on-chain Chainlink reads

### 1. Clone the repository

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials and desired parameters.

### 3. (Optional) Run tests locally

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Configuration Variables

All configuration is via environment variables (loaded from `.env`).

| Variable | Default | Description |
|---|---|---|
| `TRADING_MODE` | `dry_run` | Set to `live` to enable real orders |
| `PK` | *(required)* | Ethereum private key (hex) |
| `POLYMARKET_API_KEY` | *(required for live)* | CLOB API key |
| `POLYMARKET_API_SECRET` | *(required for live)* | CLOB API secret |
| `POLYMARKET_API_PASSPHRASE` | *(required for live)* | CLOB API passphrase |
| `CHAIN_ID` | `137` | Polygon mainnet chain ID |
| `WEB3_POLYGON_RPC` | `https://polygon-rpc.com` | Polygon RPC for Chainlink reads |
| `MAX_TRADE_USDC` | `1.0` | Maximum notional per order (USDC) |
| `DAILY_MAX_LOSS_USDC` | `10.0` | Daily loss limit before halt (USDC) |
| `DIVERGENCE_THRESHOLD` | `0.10` | Min ask price divergence to trigger entry |
| `USE_RELATIVE_DIVERGENCE` | `false` | Use relative (%) instead of absolute divergence |
| `TREND_THRESHOLD_PCT` | `0.001` | Minimum BTC return to register a trend (0.1%) |
| `OPPORTUNITY_PRICE_MAX` | `0.20` | Ask price below which opportunistic buy triggers |
| `TAKE_PROFIT_PRICE` | `0.40` | Mid price above which opportunity position is sold |
| `FLATTEN_BEFORE_SETTLEMENT` | `true` | Sell all in final 60s; false = hold if trend intact |
| `DAILY_RESET_TZ_OFFSET_HOURS` | `0` | UTC offset for daily counter reset |
| `LOOP_INTERVAL_SECS` | `1.0` | Main loop polling interval (seconds) |
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DB_PATH` | `/data/trading_bot.db` | SQLite database file path |

---

## Running with Docker

### Start the bot

```bash
docker compose up -d
```

### View live logs

```bash
docker compose logs -f
```

### Stop the bot

```bash
docker compose down
```

### Check health

```bash
docker ps
```

The healthcheck verifies the SQLite database file exists (written on startup).

---

## How the Strategy Works

### Market Discovery

The bot queries the Polymarket Gamma API for events with a slug containing
`btc-updown-5m`.  It selects the event whose start time is in the past and
end time is in the future.  When a market expires it immediately re-runs
discovery to find the next one.

### State Machine

```
OBSERVE
  │  abs(up_ask - down_ask) >= 0.10  AND  BTC trend != NEUTRAL
  ▼
ENTERED  ($1 USDC order placed in trending direction)
  │  → ask < 0.20 AND > 60s to end   → OPPORTUNITY_BUY_DONE
  │  → trend reversal detected        → sell everything → EXITED
  │  → < 60s to end                   → FINAL_MINUTE
  ▼
OPPORTUNITY_BUY_DONE  (second $1 USDC order placed)
  │  → opportunity mid > 0.40         → take-profit sell
  │  → trend reversal                 → sell everything → EXITED
  │  → < 60s to end                   → FINAL_MINUTE
  ▼
FINAL_MINUTE
  │  FLATTEN_BEFORE_SETTLEMENT=true   → sell all
  │  FLATTEN_BEFORE_SETTLEMENT=false  → hold if trend consistent
  ▼
EXITED  (next market cycle begins)
```

### Trend Signal

- 5-minute return: `(current_price / price_300s_ago) - 1`
- 15-minute return: `(current_price / price_900s_ago) - 1`
- Both positive and above threshold → **UP**
- Both negative and below threshold → **DOWN**
- Otherwise → **NEUTRAL** (no entry)

### Chainlink as Resolution Oracle

Polymarket resolves BTC Up/Down markets using the
[Chainlink BTC/USD feed on Polygon](https://data.chain.link/polygon/mainnet/crypto-usd/btc-usd).
The bot reads this feed for reference.  Binance WebSocket provides low-latency
ticks for trend signals.

---

## Daily Loss Limit

When cumulative realised losses reach `DAILY_MAX_LOSS_USDC`:

1. The Risk Manager **halts** all new order placement.
2. An `ERROR`-level log message is written.
3. At midnight in the configured timezone the counter **resets** and trading
   **resumes automatically**.

To manually resume, restart the container:

```bash
docker compose restart trading-bot
```

---

## DRY RUN Mode

DRY RUN is the **default**.  In this mode:

- Order placement calls are **skipped**.
- The bot logs what *would* have been placed with the prefix `[DRY RUN]`.
- Order books are still fetched from the live Polymarket API.
- All strategy logic, risk checks, and PnL tracking run as normal.

To enable **live trading**, set in `.env`:

```dotenv
TRADING_MODE=live
```

---

## Project Structure

```
polymarket-trading-bot/
├── polymarket/            # Polymarket CLOB client
│   ├── auth.py            # Credential management
│   ├── client.py          # CLOB API wrapper
│   ├── endpoints.py       # API URL constants
│   ├── market_discovery.py# Auto-rolling market discovery
│   └── models.py          # Data models
├── feeds/                 # BTC price feeds
│   ├── base.py            # Abstract PriceFeed
│   ├── binance.py         # Binance WebSocket + REST
│   └── chainlink.py       # Chainlink on-chain / REST
├── strategy/              # Strategy logic
│   ├── divergence.py      # Price divergence calculation
│   ├── signals.py         # Trend signals
│   └── state_machine.py   # MarketSession state machine
├── risk/                  # Risk management
│   ├── limits.py          # RiskManager
│   └── pnl.py             # PnL tracker
├── storage/               # Persistence
│   └── db.py              # SQLite wrapper
├── tests/                 # Unit tests
├── runner.py              # Main entry point
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Disclaimer

This software is provided **as-is** for educational and research purposes.
The authors assume no liability for financial losses from its use.  Prediction
markets involve significant risk.  Always verify behaviour in DRY RUN mode
before enabling live trading.
