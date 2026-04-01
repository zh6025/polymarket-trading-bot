# Architecture

## System Overview

The Polymarket BTC 5-Minute Trading Bot is a single-process Python application that polls Polymarket and Binance APIs to make automated trading decisions within 5-minute BTC price markets.

```
┌─────────────────────────────────────────────────────┐
│                   bot_runner.py                      │
│                   (Main Loop)                        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐  │
│  │ config   │   │ market_data  │   │ market_bias│  │
│  │          │   │ (Binance +   │   │ (momentum  │  │
│  │ (.env)   │   │  Polymarket) │   │  → bias)   │  │
│  └──────────┘   └──────────────┘   └────────────┘  │
│                                                     │
│  ┌──────────────────┐   ┌──────────────────────┐   │
│  │ window_strategy   │   │ session_state        │   │
│  │ (W0→Mid→W1→W2)   │   │ (per-market tracking)│   │
│  └──────────────────┘   └──────────────────────┘   │
│                                                     │
│  ┌──────────┐   ┌────────────────┐   ┌──────────┐  │
│  │execution │   │polymarket_client│  │ bot_state│  │
│  │(buy/sell)│   │(CLOB API)      │  │(persist) │  │
│  └──────────┘   └────────────────┘   └──────────┘  │
│                                                     │
│  ┌──────────┐   ┌──────────┐                       │
│  │monitoring│   │  utils   │                       │
│  └──────────┘   └──────────┘                       │
└─────────────────────────────────────────────────────┘
```

---

## Module Responsibilities

### `bot_runner.py` — Main Entry Point

The single entry point. Runs the polling loop:

1. Load config and initialize state
2. Loop forever:
   - Check global risk limits (`can_trade()`)
   - Fetch active BTC 5m market from Polymarket
   - Reset session if new market detected
   - Handle market close (close position, record PnL)
   - Fetch BTC snapshot from Binance
   - Compute bias from momentum
   - Fetch orderbook for UP/DOWN tokens
   - Run window strategy evaluation
   - Execute decision (ENTER / STOP_LOSS)
   - Update and persist state
   - Sleep (`POLLING_INTERVAL`)

### `lib/config.py` — Configuration

Loads all parameters from environment variables (via `python-dotenv`). Every tunable constant — thresholds, limits, API keys, feature flags — is an env var with a sensible default. See `.env.example` for the complete list.

### `lib/market_data.py` — Data Fetching

Two data sources:

| Source | Data | Endpoint |
|--------|------|----------|
| **Binance** | BTC spot price + 5m klines (4 candles) | `/api/v3/ticker/price`, `/api/v3/klines` |
| **Polymarket** | Orderbook (bids/asks/spread/depth) | `/book?token_id=...` |

Returns a `BtcSnapshot` with fields: `price`, `momentum_5m`, `momentum_15m`, `timestamp`.

**Caching:** BTC data is cached for 10 seconds to avoid rate limits.

**Staleness guard:** If snapshot is older than `BTC_DATA_MAX_AGE_SEC` (30s), trading is skipped.

### `lib/market_bias.py` — Bias Computation

Converts BTC momentum into a directional signal:

```
momentum_5m > +threshold AND momentum_15m > +threshold → UP
momentum_5m < -threshold AND momentum_15m < -threshold → DOWN
otherwise → NEUTRAL
```

NEUTRAL bias = no trade in any window.

### `lib/window_strategy.py` — Decision Logic

Contains four window evaluators and the `run_window_strategy()` orchestrator:

```python
def run_window_strategy(session, secs_remaining, bias, ob_up, ob_down, ...):
    if volatility_too_high:  return SKIP
    if in_window0:           return evaluate_window0(...)
    if in_mid_review:        return evaluate_mid_review(...)
    if in_window1:           return evaluate_window1(...)
    if in_window2:           return evaluate_window2(...)
    return SKIP
```

Each evaluator is a **pure function** — stateless, testable, returns a `WindowDecision`.

### `lib/session_state.py` — Per-Market Session

Tracks per-market state across polling cycles:

- Which windows have been processed (`window0_processed`, `window1_processed`, etc.)
- Open position details (direction, token, entry price, size)
- Trade outcome

Resets on each new 5-minute market via `reset_for_new_market()`.

### `lib/bot_state.py` — Global Persistence

Manages cross-market state persisted to `bot_state.json`:

- Daily PnL, trade count, consecutive losses
- Circuit breaker status
- Lifetime PnL
- Open/closed position history

**Atomic writes:** Writes to `.tmp` file then renames, preventing corruption on crash.

**Daily reset:** At UTC midnight, counters reset and circuit breaker clears.

### `lib/execution.py` — Order Execution

Thin execution layer:

| Action | Side |
|--------|------|
| `ENTER` | `BUY` |
| `STOP_LOSS` | `SELL` |

In `DRY_RUN` mode, returns synthetic `OrderResult` without hitting the API.

### `lib/polymarket_client.py` — Polymarket API

Wraps the Polymarket CLOB and Gamma APIs:

| Operation | API | Endpoint |
|-----------|-----|----------|
| Fetch market | Gamma | `GET /events/slug/{slug}` |
| Get orderbook | CLOB | `GET /book?token_id={id}` |
| Place order | CLOB | `POST /order` |
| Server time | CLOB | `HEAD /` (for clock skew correction) |

Market slug format: `btc-updown-5m-{unix_timestamp}`

### `lib/monitoring.py` — Metrics Dashboard

Provides trade metrics: 24h trade count, buy/sell breakdown, average PnL.

### `lib/utils.py` — Utilities

HTTP request helpers and logging configuration.

---

## Data Flow

```
Binance ──── BTC price + klines ────┐
                                    ▼
                              market_bias.py
                              (compute_bias)
                                    │
                                    ▼
Polymarket ── orderbook ──► window_strategy.py ──► WindowDecision
                            (evaluate windows)        │
                                                      ▼
                                               execution.py
                                              (place order)
                                                      │
                                                      ▼
                                               bot_state.py
                                              (persist PnL)
```

---

## State Management

### Two-Level State

| Level | Scope | Storage | Reset |
|-------|-------|---------|-------|
| **SessionState** | Single 5-minute market | In-memory | Each new market |
| **BotState** | Cross-market / daily | `bot_state.json` | UTC midnight |

### Crash Recovery

On startup, `BotState` is loaded from `bot_state.json`. If the file is missing or corrupted, a fresh state is created. The bot resumes trading from the next market cycle — no position recovery is attempted for in-flight orders.

---

## API Integrations

### Binance (Read-Only)

- **No API key required** — uses public endpoints only
- Ticker: `GET https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT`
- Klines: `GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=4`

### Polymarket

- **Gamma API** (market discovery): `https://gamma-api.polymarket.com`
- **CLOB API** (trading): `https://clob.polymarket.com`
- Requires `API_KEY`, `API_SECRET`, `API_PASSPHRASE` for order placement

---

## Configuration

All configuration is via environment variables loaded from `.env`:

```
Safety:     TRADING_ENABLED, DRY_RUN
Windows:    WINDOW0_ENABLED
Prices:     HARD_CAP_PRICE, MIN_CONFIDENCE_W0, MIN_CONFIDENCE_W1, LATE_ENTRY_MIN_PRICE
Quality:    MAX_SPREAD, MIN_DEPTH
Bias:       MOMENTUM_5M_THRESHOLD, MOMENTUM_15M_THRESHOLD
Volatility: MAX_RECENT_VOLATILITY, BTC_DATA_MAX_AGE_SEC
Sizing:     BET_SIZE_USDC
Risk:       DAILY_LOSS_LIMIT_USDC, DAILY_TRADE_LIMIT, CONSECUTIVE_LOSS_LIMIT
Polling:    POLLING_INTERVAL
Logging:    LOG_LEVEL
```

---

## Testing

76 unit tests covering:

| Module | Tests | Focus |
|--------|-------|-------|
| `test_window_strategy.py` | Window evaluators, orchestrator | Entry, skip, stop-loss, volatility block |
| `test_session_state.py` | Session lifecycle | Reset, position tracking, time calculation |
| `test_market_bias.py` | Bias computation | Momentum thresholds, agreement logic |
| `test_bot_state.py` | Global state | Save/load, daily reset, circuit breakers |
| `test_decision.py` | Decision gates | Hard stops, signal gates, price windows |

Run tests:
```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

---

## Directory Structure

```
polymarket-trading-bot/
├── bot_runner.py              # Main entry point
├── .env.example               # Configuration template
├── requirements.txt           # Python dependencies
├── pyproject.toml             # Project metadata
├── Dockerfile                 # Container build
├── docker-compose.yml         # Container orchestration
├── DEPLOY.md                  # Deployment quick-start
│
├── lib/                       # Core modules
│   ├── config.py              # Environment-based configuration
│   ├── bot_state.py           # Global state persistence
│   ├── session_state.py       # Per-market session tracking
│   ├── market_data.py         # Binance + Polymarket data
│   ├── market_bias.py         # BTC momentum → bias
│   ├── window_strategy.py     # Multi-window decision logic
│   ├── decision.py            # Decision data structures
│   ├── execution.py           # Order execution layer
│   ├── polymarket_client.py   # Polymarket API client
│   ├── monitoring.py          # Trade metrics
│   └── utils.py               # HTTP + logging helpers
│
├── tests/                     # Unit tests
├── docs/                      # Documentation
├── deploy/                    # Deployment scripts
└── legacy/                    # Archived V2 hedge strategy
```
