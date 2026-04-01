# Strategy V3 — Single-Direction Multi-Window BTC 5m

## Overview

Strategy V3 replaces the previous dual-sided hedge approach with a **single-direction** trading system. Each trade bets on one outcome — UP or DOWN — determined by real-time BTC momentum analysis. No simultaneous hedging is used.

The strategy targets **Polymarket BTC 5-minute markets**, where each market resolves to UP or DOWN based on whether the BTC price rose or fell during that 5-minute interval.

---

## Core Concept

```
BTC Momentum → Bias (UP / DOWN / NEUTRAL) → Window Entry → Execution
```

1. Compute a **directional bias** from 5m and 15m BTC momentum
2. Evaluate **four sequential time windows** within the market's 5-minute lifecycle
3. Enter a position only when bias, price, spread, depth, and volatility all pass
4. Use strict risk controls to limit daily losses

---

## Market Bias Computation

Bias is derived from Binance BTC/USDT kline data:

| Signal | Formula | Threshold |
|--------|---------|-----------|
| 5m momentum | `(price - price_5m_ago) / price_5m_ago` | ±0.0015 (0.15%) |
| 15m momentum | `(price - price_15m_ago) / price_15m_ago` | ±0.003 (0.30%) |

**Rules:**
- If 5m and 15m **agree** on direction and both exceed their threshold → bias = that direction
- If they **disagree** → bias = NEUTRAL (no trade)
- If only 5m data available → use 5m direction alone
- NEUTRAL bias → **skip trading** in all windows

---

## Decision Windows

Each 5-minute market is divided into four decision windows based on seconds remaining:

| Window | Seconds Remaining | Purpose | Size |
|--------|-------------------|---------|------|
| **W0** (optional) | 260 – 275 | Early momentum entry | 50% of `BET_SIZE_USDC` |
| **Mid-Review** | 115 – 125 | Stop-loss check for W0 | — |
| **W1** (primary) | 90 – 95 | Main entry point | 100% of `BET_SIZE_USDC` |
| **W2** (final) | 30 – 35 | Stop-loss or late entry | 100% of `BET_SIZE_USDC` |

Each window fires **at most once** per market (tracked by session flags).

### Window 0 — Early Momentum (Experimental)

- **Disabled by default** (`WINDOW0_ENABLED=false`)
- Requires bias alignment (UP or DOWN)
- Token price must be in `[MIN_CONFIDENCE_W0, HARD_CAP_PRICE]` → `[0.70, 0.85]`
- Spread ≤ 0.04, Depth ≥ 30
- Enters at 50% position size to manage early-entry risk

### Mid-Review — Directional Flip Check

- Only active if holding a W0 position
- If bias has **flipped** (e.g., entered UP but bias now DOWN) → **STOP_LOSS**
- If bias unchanged → no action

### Window 1 — Primary Entry

- **Most common entry point**
- Requires bias alignment (UP or DOWN)
- Token price must be in `[MIN_CONFIDENCE_W1, HARD_CAP_PRICE]` → `[0.55, 0.85]`
- Spread ≤ 0.05, Depth ≥ 50
- Enters at 100% position size

### Window 2 — Final Opportunity

- **If holding:** Stop-loss if bias flipped since entry
- **If not holding:** Late entry only if:
  - Price ≥ `LATE_ENTRY_MIN_PRICE` (0.65) — stricter than W1
  - Bias is directional
  - Spread ≤ 0.04 (tighter than W1)

---

## Hard Filters

All windows are subject to these pre-checks. If any fail, the entire cycle is skipped:

| Filter | Condition | Default |
|--------|-----------|---------|
| Volatility | 10s BTC price change > `MAX_RECENT_VOLATILITY` | 20% |
| Hard cap | Token price > `HARD_CAP_PRICE` | 0.85 |
| Spread | `best_ask - best_bid` > `MAX_SPREAD` | 0.05 |
| Depth | `bid_depth + ask_depth` < `MIN_DEPTH` | 50 USDC |
| Data staleness | BTC snapshot age > `BTC_DATA_MAX_AGE_SEC` | 30s |

---

## Risk Controls

### Circuit Breakers (Global)

| Control | Default | Behavior |
|---------|---------|----------|
| Daily loss limit | 20 USDC | Halts all trading when `daily_pnl ≤ -20` |
| Daily trade limit | 20 trades | No more trades after 20 per day |
| Consecutive losses | 3 | Stops after 3 consecutive losing trades |

Circuit breakers persist until **UTC midnight daily reset**, which clears:
- `daily_pnl`
- `daily_trade_count`
- `consecutive_losses`
- `circuit_breaker` flag

### Safety Switches

| Switch | Default | Effect |
|--------|---------|--------|
| `TRADING_ENABLED` | `false` | Observation mode — no orders placed |
| `DRY_RUN` | `true` | Simulate orders without real fills |

**Both must be intentionally changed for live trading.**

---

## Position Lifecycle

```
1. New 5m market opens
2. SessionState resets (all window flags cleared)
3. Poll every 5s:
   a. Compute bias
   b. Evaluate active window
   c. If decision = ENTER → place BUY order
   d. If decision = STOP_LOSS → place SELL order
4. Market nearing close (<5s remaining):
   a. Close any open position
   b. Record realized PnL
5. Repeat for next market
```

---

## Configuration Reference

All parameters are set via environment variables. See `.env.example` for the full list.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BET_SIZE_USDC` | 3.0 | Position size per trade |
| `HARD_CAP_PRICE` | 0.85 | Never buy above this price |
| `MIN_CONFIDENCE_W0` | 0.70 | Min price for Window 0 |
| `MIN_CONFIDENCE_W1` | 0.55 | Min price for Window 1 |
| `LATE_ENTRY_MIN_PRICE` | 0.65 | Min price for Window 2 late entry |
| `MAX_SPREAD` | 0.05 | Max bid-ask spread |
| `MIN_DEPTH` | 50.0 | Min combined depth (USDC) |
| `MOMENTUM_5M_THRESHOLD` | 0.0015 | 5m momentum threshold |
| `MOMENTUM_15M_THRESHOLD` | 0.003 | 15m momentum threshold |
| `MAX_RECENT_VOLATILITY` | 0.20 | Max 10s BTC volatility |

---

## Comparison with V2 (Legacy Hedge Strategy)

| Aspect | V2 (Legacy) | V3 (Current) |
|--------|------------|--------------|
| Direction | Dual-sided hedge (UP + DOWN) | Single-direction |
| Entry logic | Complex multi-dimensional scoring | 5m/15m momentum agreement |
| Windows | Single entry point | Four windows with escalating filters |
| Risk | Hedge offset losses | Circuit breakers + daily limits |
| Complexity | High (9-dimension scorer) | Low (momentum + thresholds) |
| Testability | Difficult (many dependencies) | High (76 unit tests) |
