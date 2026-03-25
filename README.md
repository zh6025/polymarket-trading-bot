# Polymarket Trading Bot

Automated trading bot for Polymarket BTC 5-minute Up/Down binary markets.

## Architecture

```
bot_runner.py          ← single-shot dry-run / smoke-test
bot_continuous.py      ← production continuous loop (strategy dispatch)
bot_simulate.py        ← simulation / backtesting mode
lib/
  config.py            ← env-var configuration
  polymarket_client.py ← Polymarket CLOB + Gamma API client
  direction_scorer.py  ← 9-dimension DirectionScorer (EMA/RSI/CVD/…)
  directional_strategy.py  ← EMA+ATR trend strategy
  momentum_hedge_strategy.py ← Kelly-optimal hedge strategy
  hedge_formula.py     ← hedge math (Q_h, viability, Kelly ratio)
  decision.py          ← sequential gate decision layer
  bot_state.py         ← crash-recovery state manager
  trading_engine.py    ← order execution engine
  data_persistence.py  ← SQLite persistence
  risk_manager.py      ← position-level risk checks
  monitoring.py        ← metrics / alerts
web_dashboard.py       ← Flask monitoring dashboard
tests/                 ← pytest test suite
deploy/                ← deployment scripts & configs
docs/                  ← platform comparison guides
```

## Install & Setup

```bash
git clone https://github.com/zh6025/polymarket-trading-bot.git
cd polymarket-trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API key and desired strategy
```

## Run Modes

| Command | Description |
|---|---|
| `python bot_runner.py` | Single-shot smoke test with DirectionScorer output |
| `python bot_continuous.py` | Continuous loop — production mode |
| `python bot_simulate.py` | Simulation / dry-run loop |
| `python web_dashboard.py` | Flask monitoring dashboard on :5000 |

## Strategies

Set `STRATEGY=` in `.env`:

### `imbalance` (default)
Late-entry single-side betting. Fires only when the dominant side exceeds
`DOMINANCE_THRESHOLD` (default 0.68). Strict time-window gates prevent early
entry. Safest strategy for most market conditions.

### `directional`
BTC EMA(3)/EMA(8) crossover + ATR(10) volatility filter. Fetches live 1-min
Binance klines. Only enters when volatility is high enough. Max entry price
guard prevents chasing extreme odds.

### `momentum_hedge`
Fires when the dominant side reaches `TRIGGER_THRESHOLD` (default 0.70).
Places a **hedge order first**, then the main bet. Kelly-optimal hedge ratio
minimises expected loss if the main bet loses. One-shot per market.

## DirectionScorer

The `lib/direction_scorer.py` module provides a 9-dimension signal aggregation
system for BTC 5-min direction. Signals are weighted and combined into a
sigmoid probability estimate:

| Signal | Weight | Source |
|---|---|---|
| EMA crossover | 0.15 | 1-min klines |
| RSI trend | 0.10 | 1-min klines |
| VWAP position | 0.12 | 1-min klines |
| Volume surge | 0.13 | 1-min klines |
| CVD direction | 0.18 | Order flow data |
| Orderbook ratio | 0.15 | CLOB depth |
| Funding rate | 0.07 | Perpetual futures |
| OI change | 0.05 | Perpetual futures |
| Macro sentiment | 0.05 | External |

## Hedge Formula

The optimal hedge quantity is:

```
Q_h = (P_m × Q_m) / ((1 − P_h) × (1 − f))
```

Strategy is viable when:

```
(1 − P_m)(1 − P_h)(1 − f)² > P_m × P_h
```

Optimal entry ranges: Main `P_m ∈ [0.50, 0.65]` · Hedge `P_h ∈ [0.05, 0.15]`

## Risk Controls

- `DAILY_LOSS_LIMIT_USDC` — stop trading after this loss (default 20 USDC)
- `DAILY_TRADE_LIMIT` — max trades per UTC day (default 20)
- `CONSECUTIVE_LOSS_LIMIT` — pause after N consecutive losses (default 3)
- `HARD_STOP_NEW_ENTRY_SEC` — no new entries in last N seconds (default 30)
- `MAIN_MAX_PRICE` — max entry price for main leg (default 0.66)

All state is persisted atomically to `bot_state.json` for crash recovery.

## Configuration

See `.env.example` for all variables. Key variables:

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | — | Polymarket CLOB API key |
| `DRY_RUN` | `true` | Simulate only (no real orders) |
| `TRADING_ENABLED` | `false` | Enable real order placement |
| `STRATEGY` | `imbalance` | Strategy selection |
| `DAILY_LOSS_LIMIT_USDC` | `20` | Daily loss limit |
| `MAIN_BET_SIZE_USDC` | `3.0` | Main leg notional |
| `DOMINANCE_THRESHOLD` | `0.68` | Imbalance trigger |
| `TRIGGER_THRESHOLD` | `0.70` | Momentum hedge trigger |
| `ENABLE_HEDGE` | `false` | Enable hedge leg |

## Docker Deployment

```bash
docker-compose up -d bot
docker-compose logs -f bot
```

For production: see `deploy/DEPLOYMENT_GUIDE.md`

## Cloud Deployment

- **Linode/Vultr**: `deploy/setup-linode.sh` + `deploy/deploy.sh`
- **Railway**: connect GitHub repo, set env vars, command: `python bot_continuous.py`
- **Comparison**: `docs/railway-vs-vultr.md`

## Tests

```bash
pytest tests/ -v
```

## License

MIT
