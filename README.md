# Polymarket Grid Trading Bot

Automated grid trading bot for Polymarket binary outcome markets (e.g. BTC Up/Down 5-minute events).

## Project Structure

```
polymarket-trading-bot/
├── lib/
│   ├── utils.js        # HTTP requests, decompression, logging, time helpers
│   ├── polymarket.js   # Polymarket API client (markets, CLOB orderbook)
│   ├── strategy.js     # Grid trading strategy engine
│   ├── risk.js         # Risk management and position control
│   └── config.js       # Configuration from environment variables
├── scripts/
│   ├── plan-grid-dryrun.js      # One-shot grid dry-run (uses lib/)
│   ├── watch-grid-dryrun.js     # Continuous watch dry-run (uses lib/)
│   ├── find-live-btc-5m.js      # Discover latest open BTC 5m event
│   ├── probe-orderbook.js       # Probe CLOB orderbook endpoints
│   └── ...                      # Other debug / exploration scripts
├── bot-runner.js       # Main entry point
├── .env.example        # Configuration template
└── package.json
```

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set SLUG (or leave blank for auto-discovery)

# 3. Dry-run test
node bot-runner.js --dry-run

# 4. One-shot plan (no loop)
node scripts/plan-grid-dryrun.js

# 5. Continuous watch (dry-run)
node scripts/watch-grid-dryrun.js
```

## Configuration

All settings are read from environment variables (or `.env`). See `.env.example` for the full list.

| Variable              | Default               | Description                                      |
|-----------------------|-----------------------|--------------------------------------------------|
| `SLUG`                | *(auto-discover)*     | Polymarket event slug to trade                   |
| `SERIES_SLUG`         | `btc-up-or-down-5m`   | Series slug for auto-discovery                   |
| `LEVELS_EACH_SIDE`    | `5`                   | Grid levels on each side of mid                  |
| `GRID_STEP`           | `0.02`                | Price step between levels                        |
| `ORDER_SIZE`          | `5`                   | USDC order size per level                        |
| `TRADE_BOTH_OUTCOMES` | `true`                | Trade both Up and Down outcomes                  |
| `INTERVAL_MS`         | `5000`                | Polling interval (ms)                            |
| `DRY_RUN`             | `true`                | Print orders without placing them                |
| `MAX_DAILY_LOSS_USDC` | `50`                  | Circuit breaker: stop if daily loss exceeds this |
| `MAX_POSITION_USDC`   | `200`                 | Maximum total open position (USDC)               |
| `PM_API_KEY`          |                       | Polymarket CLOB API key (live trading only)      |
| `PM_PRIVATE_KEY`      |                       | Ethereum private key (live trading only)         |

## Architecture

### lib/utils.js
Common infrastructure: HTTP GET with gzip/brotli/deflate decompression, `sleep`, `toTime`, and a levelled logger (`log.info`, `log.warn`, `log.error`, `log.debug`).

### lib/polymarket.js
Polymarket API client:
- `fetchSeries(seriesSlug)` — series and events list
- `fetchEventBySlug(eventSlug)` — event details with markets
- `findLatestOpenEvent(seriesSlug)` — auto-discover current open event
- `fetchMarketFromEventPage(slug)` — extract market from HTML `__NEXT_DATA__`
- `fetchBook(tokenId)` — CLOB orderbook
- `bestBidAsk(book)`, `calcMid(book)` — price helpers
- `roundToTick(price, tickSize)` — price rounding

### lib/strategy.js
Grid trading strategy:
- `makeGridLevels(mid, tickSize, step, levelsEachSide)` — generate price levels
- `buildGridPlan(opts)` — single-outcome order plan
- `buildUpDownGridPlan(opts)` — Up + Down order plan

### lib/risk.js
`RiskManager` class:
- Daily PnL tracking with automatic midnight reset
- Position size limits
- Circuit breaker (halts when daily loss exceeds `maxDailyLossUsdc`)
- `checkOrder(order)` — returns `{ allowed, reason }`

### lib/config.js
`loadConfig()` — reads all environment variables with sensible defaults.

## Live Trading

Live order submission requires `PM_API_KEY` and `PM_PRIVATE_KEY`. Set `DRY_RUN=false` in `.env`.

> **Warning:** Live trading involves real financial risk. Always test thoroughly in dry-run mode first.

## Debug Scripts

The `scripts/` directory contains exploration and debugging tools inherited from the initial research phase. They can be run standalone:

```bash
node scripts/find-live-btc-5m.js
node scripts/probe-orderbook.js
```
