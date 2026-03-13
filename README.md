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

## 🚀 Quick Start – Testing / Simulation (快速开始 – 测试/模拟)

### Step 1: 离线模拟（无需任何密钥）| Offline simulation – zero credentials needed

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the offline simulator – no API keys, no real money
python simulate.py                          # 3 cycles, mixed scenarios
python simulate.py --cycles 5               # run 5 market cycles
python simulate.py --scenario trending_up   # strong uptrend scenario
python simulate.py --scenario trending_down # strong downtrend scenario
python simulate.py --scenario volatile      # extreme price swings
python simulate.py --scenario ranging       # sideways market (bot mostly observes)
```

The simulator uses **synthetic BTC prices and synthetic order books** — it
exercises the complete strategy loop (state machine, risk limits, PnL
tracking) without touching any network or exchange.

### Step 2: 盘口干跑（读取真实盘口，不下单）| DRY RUN with live orderbook – no real orders

```bash
# 1. Copy the ready-made dry-run config (no real credentials needed)
cp .env.dry_run .env

# 2. Start the bot – reads live Polymarket orderbooks, places NO real orders
python runner.py

# Or with Docker:
docker compose up
```

All actions are logged as `[DRY RUN]`. Your wallet address is pre-configured.
No private key or API credentials are required for dry-run order-book reads.

### Step 3: 实盘交易 | Live trading – real money

Only when you are satisfied with dry-run behaviour:

```bash
cp .env.example .env
# Edit .env and set:
#   TRADING_MODE=live
#   PK=0xYOUR_PRIVATE_KEY
#   POLYMARKET_API_KEY / SECRET / PASSPHRASE
docker compose up -d
```

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
| `PK` | *(required for live)* | Ethereum private key (hex) |
| `POLYMARKET_FUNDER_ADDRESS` | `0xe95ce742…` | Your Polymarket wallet address (pre-filled) |
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
| `DAILY_RESET_TZ_OFFSET_HOURS` | `0` | UTC offset for daily counter reset (8 = CST) |
| `LOOP_INTERVAL_SECS` | `1.0` | Main loop polling interval (seconds) |
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DB_PATH` | `/data/trading_bot.db` | SQLite database file path |

### About `POLYMARKET_FUNDER_ADDRESS`

Your Polymarket username is `0xe95ce742AfC2977965998810f326192D1593c1E1-1772245217002`.
The address part (`0xe95ce742AfC2977965998810f326192D1593c1E1`) is pre-filled as the
default value for `POLYMARKET_FUNDER_ADDRESS`.  This is the Polygon wallet address
that holds your USDC and is linked to your Polymarket CLOB API keys.  You do **not**
need to change it unless you use a different wallet.

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
- **No private key is required** — order books are public endpoints.

To enable **live trading**, set in `.env`:

```dotenv
TRADING_MODE=live
```

---

## Offline Simulation (`simulate.py`)

For testing with **zero network access and zero credentials**, use the
offline simulator:

```bash
python simulate.py [--cycles N] [--scenario SCENARIO] [--seed INT]
```

| Scenario | Description |
|---|---|
| `trending_up` | BTC rises steadily → expects UP entries, profit on flatten |
| `trending_down` | BTC falls steadily → expects DOWN entries |
| `ranging` | Sideways market – prices stay close, bot mostly observes |
| `volatile` | Sharp reversals – tests reversal-exit and opportunity-buy logic |
| `mixed` (default) | Cycles through trending_up → trending_down → ranging |

**What it does:**

1. Generates synthetic BTC prices with configurable trend and volatility
2. Builds realistic UP/DOWN order books from those prices
3. Runs the complete strategy state machine tick-by-tick
4. Prints every decision with timestamp, price, and PnL
5. Shows a summary table at the end

**Example output:**

```
════════════════════════════════════════════════════════════════
 Polymarket BTC Up/Down 5m – OFFLINE SIMULATION (模拟交易)
════════════════════════════════════════════════════════════════
 Cycles   : 3  |  Scenario : mixed  |  Seed : 42

[12:00:01] [Cycle 1]   Scenario: trending_up
[12:00:01]   OBSERVE   s=  0s  up_ask=0.510  down_ask=0.510  div=0.000
[12:00:01]   BUY (initial)  s=43s  UP  price=0.560  trend=UP  BTC=$83,000
[12:00:01]   SELL (final)   s=241s  UP  sell=0.771  pnl=+0.2110
[12:00:01] [Cycle 1 END]  realised_pnl = +0.2110 USDC

  SIMULATION SUMMARY
  Cycle    Scenario        PnL (USDC)
  1        trending_up        +0.2110
  2        trending_down      +0.2110
  3        ranging            +0.0000
  TOTAL                       +0.4220
```

---

## Project Structure

```
polymarket-trading-bot/
├── polymarket/            # Polymarket CLOB client
│   ├── auth.py            # Credential management + funder address
│   ├── client.py          # CLOB API wrapper (read-only if no PK)
│   ├── endpoints.py       # API URL constants (Gamma, CLOB, Binance, Chainlink)
│   ├── market_discovery.py# Auto-rolling market discovery via Gamma API
│   └── models.py          # Data models
├── feeds/                 # BTC price feeds
│   ├── base.py            # Abstract PriceFeed with rolling history
│   ├── binance.py         # Binance WebSocket + REST fallback
│   └── chainlink.py       # Chainlink on-chain / REST fallback
├── strategy/              # Strategy logic
│   ├── divergence.py      # Price divergence calculation
│   ├── signals.py         # 5m/15m trend signals
│   └── state_machine.py   # MarketSession state machine
├── risk/                  # Risk management
│   ├── limits.py          # RiskManager (daily loss, per-trade, circuit breaker)
│   └── pnl.py             # PnL tracker
├── storage/               # Persistence
│   └── db.py              # SQLite wrapper
├── tests/                 # Unit tests (76 tests)
├── runner.py              # Main entry point (live + dry-run)
├── simulate.py            # Offline simulation (zero credentials)
├── .env.example           # Full config template
├── .env.dry_run           # Ready-to-use dry-run config (no keys needed)
├── Dockerfile
├── docker-compose.yml
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
