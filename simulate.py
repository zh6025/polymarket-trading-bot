"""
Offline simulation of one or more 5-minute BTC Up/Down market cycles.

No API keys, no network access, no real money.  Uses synthetic BTC price
data and synthetic order books to exercise the full strategy state machine.

Usage
-----
    python simulate.py                          # 3 cycles, "mixed" scenario
    python simulate.py --cycles 5               # 5 cycles
    python simulate.py --scenario trending_up   # strong uptrend
    python simulate.py --scenario trending_down # strong downtrend
    python simulate.py --scenario ranging       # sideways market
    python simulate.py --scenario volatile      # sharp reversals

Scenarios
---------
    trending_up   – BTC rises steadily → expect UP entries
    trending_down – BTC falls steadily → expect DOWN entries
    ranging       – prices stay close; bot mostly observes
    volatile      – sudden drops create <0.20 opportunity buys
    mixed         – one cycle each of up, down, ranging (default)

Output
------
The simulation prints a timestamped, human-readable log to stdout.  A
summary table is shown at the end showing PnL per cycle.

All trades are DRY RUN (虚拟交易) — nothing is sent to any exchange.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── set env BEFORE importing any bot modules ──────────────────────────────
os.environ["TRADING_MODE"] = "dry_run"
os.environ["DB_PATH"] = str(Path("/tmp") / "sim_trading_bot.db")
os.environ["LOG_LEVEL"] = "WARNING"   # suppress noisy structlog output

import logging

logging.basicConfig(
    stream=sys.stdout,
    level=logging.WARNING,
    format="%(message)s",
)

# ── bot imports ────────────────────────────────────────────────────────────
from feeds.base import PriceFeed
from polymarket.models import (
    MarketInfo,
    Order,
    OrderBook,
    OrderStatus,
    Outcome,
    Side,
)
from risk.limits import RiskLimits, RiskManager
from storage.db import Database
from strategy.divergence import get_ask_prices, is_diverged
from strategy.signals import Trend, get_trend, is_trend_reversal
from strategy.state_machine import MarketSession, MarketState


# ── ANSI colours ──────────────────────────────────────────────────────────
_RESET = "\033[0m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _log(color: str, label: str, msg: str) -> None:
    print(f"{_DIM}[{_ts()}]{_RESET} {color}{_BOLD}{label:<18}{_RESET} {msg}")


# ══════════════════════════════════════════════════════════════════════════
# Synthetic price feed
# ══════════════════════════════════════════════════════════════════════════

class SyntheticBTCFeed(PriceFeed):
    """Generates deterministic synthetic BTC/USD tick data.

    Builds a full 15-minute history immediately so trend signals have data
    from the very first second of simulation.
    """

    def __init__(
        self,
        start_price: float = 83_000.0,
        trend_pct_per_min: float = 0.0,
        volatility_pct: float = 0.05,
        seed: int = 42,
    ) -> None:
        super().__init__()
        self._trend = trend_pct_per_min / 100.0
        self._vol = volatility_pct / 100.0
        self._rng = random.Random(seed)
        self._price = start_price
        self._running = False

        # Pre-fill 16 minutes of history so trend signals work immediately
        now = time.time()
        for i in range(960, 0, -1):
            past_ts = now - i
            noise = self._rng.gauss(0, self._vol * start_price)
            price = start_price * (1 + self._trend * (-i / 60)) + noise
            self._record(max(price, 1.0), past_ts)

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def tick(self, elapsed_seconds: float) -> float:
        """Advance the price by one second and return the new price."""
        noise = self._rng.gauss(0, self._vol * self._price)
        self._price = max(self._price * (1 + self._trend / 60) + noise, 1.0)
        self._record(self._price)
        return self._price


# ══════════════════════════════════════════════════════════════════════════
# Synthetic order book provider
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class SyntheticOrderBooks:
    """Generates realistic UP/DOWN order books from a probability estimate.

    *prob_up* is the current market probability that BTC goes UP
    (0 = certain DOWN, 1 = certain UP).  A natural spread of 2-3% is
    added to each side.
    """

    prob_up: float = 0.50
    spread: float = 0.02   # bid-ask spread on each side

    def get_book(self, outcome: Outcome) -> OrderBook:
        if outcome == Outcome.UP:
            mid = self.prob_up
        else:
            mid = 1.0 - self.prob_up

        bid = max(mid - self.spread / 2, 0.01)
        ask = min(mid + self.spread / 2, 0.99)
        book = OrderBook(token_id=f"synthetic-{outcome.value}")
        book.bids = [(round(bid, 4), 50.0)]
        book.asks = [(round(ask, 4), 50.0)]
        return book

    def update(
        self,
        elapsed: float,
        total: float,
        btc_return_5m: Optional[float],
        scenario: str,
    ) -> None:
        """Update the implied probability based on the scenario."""
        frac = elapsed / total  # 0 → 1 as market progresses

        if scenario == "trending_up":
            self.prob_up = min(0.50 + frac * 0.35, 0.88)
        elif scenario == "trending_down":
            self.prob_up = max(0.50 - frac * 0.35, 0.12)
        elif scenario == "volatile":
            # Drop sharply to create <0.20 opportunity, then recover
            if frac < 0.3:
                self.prob_up = 0.50
            elif frac < 0.45:
                # DOWN side crashes below 0.20
                self.prob_up = min(0.50 + frac * 0.5, 0.85)
            else:
                self.prob_up = 0.65
        elif scenario == "ranging":
            self.prob_up = 0.50 + 0.04 * math.sin(frac * 4 * math.pi)
        else:  # mixed / default
            self.prob_up = 0.50


# ══════════════════════════════════════════════════════════════════════════
# Dry-run order stub
# ══════════════════════════════════════════════════════════════════════════

_order_counter = 0


def _make_sim_order(
    market_id: str,
    token_id: str,
    outcome: Outcome,
    side: Side,
    price: float,
    size_usdc: float,
) -> Order:
    global _order_counter
    _order_counter += 1
    return Order(
        order_id=f"SIM-{_order_counter:04d}",
        market_id=market_id,
        token_id=token_id,
        outcome=outcome,
        side=side,
        price=price,
        size=size_usdc,
        status=OrderStatus.FILLED,
        filled_size=size_usdc,
        avg_fill_price=price,
        created_at=time.time(),
    )


# ══════════════════════════════════════════════════════════════════════════
# Single-cycle simulation
# ══════════════════════════════════════════════════════════════════════════

MARKET_DURATION = 300   # seconds (one 5-minute market = 300 ticks, each tick = 1 sim-second)
TICK_INTERVAL   = 1.0   # seconds per simulated tick

DIVERGENCE_THRESHOLD = 0.10
OPPORTUNITY_PRICE_MAX = 0.20
TAKE_PROFIT_PRICE = 0.40
MAX_TRADE_USDC = 1.0
FLATTEN_BEFORE_SETTLEMENT = True
TREND_THRESHOLD_PCT = 0.001


def simulate_cycle(
    cycle_num: int,
    scenario: str,
    feed: SyntheticBTCFeed,
    risk: RiskManager,
    db: Database,
    seed: int = 0,
) -> float:
    """Run one 5-minute market cycle.  Returns realised PnL (USDC)."""

    market_id = f"sim-market-{cycle_num:04d}"
    now = time.time()
    end_ts = now + MARKET_DURATION

    market = MarketInfo(
        market_id=market_id,
        question="BTC Up or Down - 5 Minutes (Simulation)",
        token_id_up=f"{market_id}-UP",
        token_id_down=f"{market_id}-DOWN",
        end_date_iso=datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
        end_timestamp=end_ts,
        active=True,
        slug=f"btc-updown-5m-sim-{cycle_num}",
    )

    session = MarketSession(market=market)
    books = SyntheticOrderBooks(prob_up=0.50)
    initial_trend: Optional[Trend] = None
    realised_pnl = 0.0

    _log(_CYAN, f"[Cycle {cycle_num}]", f"Scenario: {_BOLD}{scenario}{_RESET}  "
         f"Market: {market_id}")

    for sim_second in range(MARKET_DURATION):
        elapsed = float(sim_second)
        secs_left = MARKET_DURATION - elapsed

        # Advance the synthetic price feed
        btc_price = feed.tick(elapsed)

        # Update synthetic order books
        ret_5m = feed.price_n_seconds_ago(300)
        btc_return_5m = (btc_price / ret_5m - 1) if ret_5m else None
        books.update(elapsed, float(MARKET_DURATION), btc_return_5m, scenario)

        book_up   = books.get_book(Outcome.UP)
        book_down = books.get_book(Outcome.DOWN)
        up_ask, down_ask = get_ask_prices(book_up, book_down)

        # ── OBSERVE ────────────────────────────────────────────────────
        if session.state == MarketState.OBSERVE:
            if up_ask is None or down_ask is None:
                continue
            if not is_diverged(up_ask, down_ask, DIVERGENCE_THRESHOLD):
                if sim_second % 30 == 0:
                    _log(_DIM, "  OBSERVE",
                         f"s={sim_second:3d}s  up_ask={up_ask:.3f}  "
                         f"down_ask={down_ask:.3f}  "
                         f"div={abs(up_ask-down_ask):.3f} (need ≥{DIVERGENCE_THRESHOLD})")
                continue

            trend = get_trend(feed, TREND_THRESHOLD_PCT)
            if trend == Trend.NEUTRAL:
                continue

            allowed, reason = risk.can_enter(market_id, MAX_TRADE_USDC, secs_left)
            if not allowed:
                _log(_YELLOW, "  BLOCKED", reason)
                continue

            outcome = Outcome.UP if trend == Trend.UP else Outcome.DOWN
            entry_price = up_ask if outcome == Outcome.UP else down_ask
            order = _make_sim_order(
                market_id, market.token_id_up if outcome == Outcome.UP else market.token_id_down,
                outcome, Side.BUY, entry_price, MAX_TRADE_USDC,
            )
            session.initial_order = order
            session.initial_outcome = outcome
            session.initial_entry_price = entry_price
            initial_trend = trend
            risk.record_entry(market_id)
            db.upsert_order(order)
            session.transition(MarketState.ENTERED)

            _log(_GREEN, "  BUY (initial)",
                 f"s={sim_second:3d}s  {outcome.value}  price={entry_price:.3f}  "
                 f"trend={trend.value}  BTC=${btc_price:,.0f}")

        # ── ENTERED / OPPORTUNITY_BUY_DONE ─────────────────────────────
        elif session.state in (MarketState.ENTERED, MarketState.OPPORTUNITY_BUY_DONE):

            if secs_left <= 60:
                session.transition(MarketState.FINAL_MINUTE)
                continue

            current_trend = get_trend(feed, TREND_THRESHOLD_PCT)

            # Trend reversal check
            if initial_trend and is_trend_reversal(initial_trend, current_trend):
                sell_price = (book_up if session.initial_outcome == Outcome.UP
                              else book_down).best_bid or session.initial_entry_price
                pnl = (sell_price - session.initial_entry_price) * MAX_TRADE_USDC
                realised_pnl += pnl
                _log(_RED, "  SELL (reversal)",
                     f"s={sim_second:3d}s  {session.initial_outcome.value}  "
                     f"sell={sell_price:.3f}  pnl={pnl:+.4f}")

                if session.opportunity_order:
                    opp_outcome = session.opportunity_outcome
                    opp_book = book_up if opp_outcome == Outcome.UP else book_down
                    opp_sell = opp_book.best_bid or session.opportunity_entry_price
                    opp_pnl = (opp_sell - session.opportunity_entry_price) * MAX_TRADE_USDC
                    realised_pnl += opp_pnl
                    _log(_RED, "  SELL (opp rev)",
                         f"s={sim_second:3d}s  {opp_outcome.value}  "
                         f"sell={opp_sell:.3f}  pnl={opp_pnl:+.4f}")

                session.transition(MarketState.EXITED)
                break

            # Opportunity buy
            if (session.state == MarketState.ENTERED
                    and session.has_opportunity_slot and secs_left > 60):
                opp_ask: Optional[float] = None
                opp_outcome: Optional[Outcome] = None
                opp_token: Optional[str] = None

                if up_ask is not None and up_ask < OPPORTUNITY_PRICE_MAX:
                    opp_ask, opp_outcome, opp_token = up_ask, Outcome.UP, market.token_id_up
                elif down_ask is not None and down_ask < OPPORTUNITY_PRICE_MAX:
                    opp_ask, opp_outcome, opp_token = down_ask, Outcome.DOWN, market.token_id_down

                if opp_ask is not None:
                    allowed, _ = risk.can_enter(market_id, MAX_TRADE_USDC, secs_left)
                    if allowed:
                        opp_order = _make_sim_order(
                            market_id, opp_token, opp_outcome,  # type: ignore[arg-type]
                            Side.BUY, opp_ask, MAX_TRADE_USDC,
                        )
                        session.opportunity_order = opp_order
                        session.opportunity_outcome = opp_outcome
                        session.opportunity_entry_price = opp_ask
                        risk.record_entry(market_id)
                        db.upsert_order(opp_order)
                        session.transition(MarketState.OPPORTUNITY_BUY_DONE)
                        _log(_YELLOW, "  BUY (opp <0.20)",
                             f"s={sim_second:3d}s  {opp_outcome.value}  "  # type: ignore[union-attr]
                             f"price={opp_ask:.3f}  BTC=${btc_price:,.0f}")

            # Take-profit on opportunity position
            if session.opportunity_order and session.opportunity_outcome:
                opp_book = (book_up if session.opportunity_outcome == Outcome.UP
                            else book_down)
                opp_mid = opp_book.mid
                if opp_mid is not None and opp_mid > TAKE_PROFIT_PRICE:
                    pnl = (opp_mid - session.opportunity_entry_price) * MAX_TRADE_USDC
                    realised_pnl += pnl
                    _log(_GREEN, "  SELL (take-profit)",
                         f"s={sim_second:3d}s  {session.opportunity_outcome.value}  "
                         f"mid={opp_mid:.3f}  pnl={pnl:+.4f}")
                    session.opportunity_order = None

        # ── FINAL_MINUTE ───────────────────────────────────────────────
        if session.state == MarketState.FINAL_MINUTE:
            if FLATTEN_BEFORE_SETTLEMENT:
                if session.initial_order:
                    sell_price = (book_up if session.initial_outcome == Outcome.UP
                                  else book_down).best_bid or session.initial_entry_price
                    pnl = (sell_price - session.initial_entry_price) * MAX_TRADE_USDC
                    realised_pnl += pnl
                    _log(_CYAN, "  SELL (final min)",
                         f"s={sim_second:3d}s  {session.initial_outcome.value}  "
                         f"sell={sell_price:.3f}  pnl={pnl:+.4f}")
                if session.opportunity_order and session.opportunity_outcome:
                    opp_book = (book_up if session.opportunity_outcome == Outcome.UP
                                else book_down)
                    sell_price = opp_book.best_bid or session.opportunity_entry_price
                    pnl = (sell_price - session.opportunity_entry_price) * MAX_TRADE_USDC
                    realised_pnl += pnl
                    _log(_CYAN, "  SELL (final opp)",
                         f"s={sim_second:3d}s  {session.opportunity_outcome.value}  "
                         f"sell={sell_price:.3f}  pnl={pnl:+.4f}")
            session.transition(MarketState.EXITED)
            break

        if session.state == MarketState.EXITED:
            break

    # Market settled without exit – treat as held to settlement
    if session.state not in (MarketState.EXITED, MarketState.FINAL_MINUTE):
        _log(_DIM, "  SETTLED", f"No open position at settlement.")

    color = _GREEN if realised_pnl >= 0 else _RED
    _log(color, f"[Cycle {cycle_num} END]",
         f"realised_pnl = {color}{_BOLD}{realised_pnl:+.4f} USDC{_RESET}  "
         f"state={session.state.value}")

    if realised_pnl < 0:
        risk.update_daily_loss(-realised_pnl)
    risk.reset_market(market_id)

    return realised_pnl


# ══════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════

_SCENARIOS = ["trending_up", "trending_down", "ranging", "volatile", "mixed"]

_SCENARIO_FEEDS = {
    "trending_up":   dict(trend_pct_per_min=+0.08, volatility_pct=0.03),
    "trending_down": dict(trend_pct_per_min=-0.08, volatility_pct=0.03),
    "ranging":       dict(trend_pct_per_min=0.0,   volatility_pct=0.01),
    "volatile":      dict(trend_pct_per_min=+0.04, volatility_pct=0.12),
    "mixed":         None,  # handled specially
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Polymarket BTC 5m trading bot simulation"
    )
    parser.add_argument(
        "--cycles", type=int, default=3,
        help="Number of 5-minute market cycles to simulate (default: 3)",
    )
    parser.add_argument(
        "--scenario", choices=_SCENARIOS, default="mixed",
        help="Market scenario to simulate (default: mixed)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    print(f"\n{_BOLD}{_CYAN}{'═'*64}")
    print(" Polymarket BTC Up/Down 5m – OFFLINE SIMULATION (模拟交易)")
    print(f"{'═'*64}{_RESET}\n")
    print(f" Cycles   : {args.cycles}")
    print(f" Scenario : {args.scenario}")
    print(f" Seed     : {args.seed}")
    print(f" Mode     : DRY RUN – no real orders, no real money")
    print(f" Address  : 0xe95ce742AfC2977965998810f326192D1593c1E1 (read-only)\n")

    db = Database(Path(os.environ["DB_PATH"]))
    risk = RiskManager(
        limits=RiskLimits(
            max_trade_usdc=MAX_TRADE_USDC,
            daily_max_loss_usdc=10.0,
        )
    )

    results: list[tuple[int, str, float]] = []

    for cycle_num in range(1, args.cycles + 1):
        if args.scenario == "mixed":
            scenario = _SCENARIOS[(cycle_num - 1) % (len(_SCENARIOS) - 1)]
        else:
            scenario = args.scenario

        feed_kwargs = _SCENARIO_FEEDS.get(scenario) or _SCENARIO_FEEDS["ranging"]
        assert feed_kwargs is not None
        feed = SyntheticBTCFeed(seed=args.seed + cycle_num, **feed_kwargs)
        feed.start()

        if risk.is_halted:
            _log(_RED, f"[Cycle {cycle_num}]",
                 f"Risk halted ({risk.halt_reason}) – skipping cycle")
            results.append((cycle_num, scenario, 0.0))
            continue

        pnl = simulate_cycle(cycle_num, scenario, feed, risk, db, seed=args.seed)
        results.append((cycle_num, scenario, pnl))
        feed.stop()
        print()

    # ── Summary ────────────────────────────────────────────────────────
    total_pnl = sum(r[2] for r in results)
    print(f"\n{_BOLD}{'─'*64}")
    print(f"  SIMULATION SUMMARY (模拟结果汇总)")
    print(f"{'─'*64}{_RESET}")
    print(f"  {'Cycle':<8} {'Scenario':<16} {'PnL (USDC)':>12}")
    print(f"  {'─'*6:<8} {'─'*14:<16} {'─'*12:>12}")
    for cyc, scen, pnl in results:
        color = _GREEN if pnl >= 0 else _RED
        print(f"  {cyc:<8} {scen:<16} {color}{pnl:>+12.4f}{_RESET}")
    print(f"  {'─'*6:<8} {'─'*14:<16} {'─'*12:>12}")
    total_color = _GREEN if total_pnl >= 0 else _RED
    print(f"  {'TOTAL':<8} {'':<16} "
          f"{total_color}{_BOLD}{total_pnl:>+12.4f}{_RESET}")
    print(f"\n  Daily loss tracker : {risk.daily_loss:.4f} / 10.0000 USDC")
    print(f"  Risk halted        : {risk.is_halted}")
    print()

    db.close()


if __name__ == "__main__":
    main()
