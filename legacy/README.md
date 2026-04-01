# Legacy Code

This directory contains code from the previous hedge-based strategy architecture.
It has been superseded by the new single-side multi-window BTC 5-minute strategy.

## Contents

| File | Original path | Description |
|------|--------------|-------------|
| `bot_continuous.py` | `bot_continuous.py` | Old continuous bot loop |
| `bot_simulate.py` | `bot_simulate.py` | Old simulation runner |
| `web_dashboard.py` | `web_dashboard.py` | Old web dashboard |
| `lib_hedge_formula.py` | `lib/hedge_formula.py` | Hedge math formulas |
| `lib_direction_scorer.py` | `lib/direction_scorer.py` | 9-dimension direction scorer |
| `lib_trading_engine.py` | `lib/trading_engine.py` | Old order execution engine |
| `lib_strategy.py` | `lib/strategy.py` | Old strategy module |
| `lib_profit_strategy.py` | `lib/profit_strategy.py` | Old profit strategy |
| `lib_risk.py` | `lib/risk.py` | Old risk utilities |
| `lib_risk_manager.py` | `lib/risk_manager.py` | Old risk manager |
| `lib_data_persistence.py` | `lib/data_persistence.py` | Old SQLite persistence |
| `test_hedge_formula.py` | `tests/test_hedge_formula.py` | Tests for hedge formula |
| `test_direction_scorer.py` | `tests/test_direction_scorer.py` | Tests for direction scorer |

## New Architecture

The new architecture lives in the root and `lib/` directory:

- `bot_runner.py` — main entry point, multi-window loop
- `lib/session_state.py` — per-market session tracking
- `lib/market_data.py` — BTC and orderbook data fetching
- `lib/market_bias.py` — UP/DOWN/NEUTRAL bias from BTC momentum
- `lib/window_strategy.py` — multi-window decision logic
- `lib/execution.py` — order execution layer
