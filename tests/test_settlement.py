"""Tests for live-trading safeguards added on the way to real-money trading.

Covers:
  * BotState persistence of last_entered_window_ts / pending_entry across save+load
  * lib.trade_journal append-only JSONL writes
  * SniperBot._preflight_balance gating
  * SniperBot._settle_pending_entry happy path (won), loss path, partial fill,
    no-fill (cancel-only), and "still unresolved → wait next cycle"
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from lib.bot_state import BotState
from lib import trade_journal


# ---------------------------------------------------------------------------
# BotState persistence of new fields
# ---------------------------------------------------------------------------
class TestBotStatePendingEntry:
    def test_pending_entry_roundtrip(self, tmp_path):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = str(tmp_path / "state.json")
        s = BotState()
        s.current_date = today
        s.last_entered_window_ts = 1700000000
        s.pending_entry = {
            "slug": "btc-updown-5m-1700000000",
            "window_open_ts": 1700000000,
            "window_end_ts": 1700000300,
            "direction": "UP",
            "token_id": "tok-123",
            "condition_id": "cond-abc",
            "entry_price": 0.57,
            "shares_requested": 5.26,
            "notional_usdc": 3.0,
            "order_id": "ord-1",
            "submit_ts": 1700000270,
            "settled": False,
            "settle_attempts": 0,
        }
        s.save(path)

        loaded = BotState.load(path)
        assert loaded.last_entered_window_ts == 1700000000
        assert isinstance(loaded.pending_entry, dict)
        assert loaded.pending_entry["direction"] == "UP"
        assert loaded.pending_entry["entry_price"] == 0.57

    def test_defaults_when_loading_legacy_file(self, tmp_path):
        """An older state.json without the new fields should still load cleanly."""
        path = str(tmp_path / "legacy.json")
        with open(path, "w") as f:
            # mimic a previous-version state file
            json.dump({
                "trading_enabled": True,
                "daily_pnl": -1.5,
                "current_date": "2099-01-01",
                "total_pnl": 3.0,
            }, f)
        loaded = BotState.load(path)
        assert loaded.last_entered_window_ts is None
        assert loaded.pending_entry is None


# ---------------------------------------------------------------------------
# trade_journal
# ---------------------------------------------------------------------------
class TestTradeJournal:
    def test_append_writes_jsonline(self, tmp_path):
        path = str(tmp_path / "trades.jsonl")
        trade_journal.append("submit", {"slug": "x", "shares": 1.0}, path=path)
        trade_journal.append("settle", {"slug": "x", "pnl": 0.42}, path=path)

        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2
        assert lines[0]["event"] == "submit"
        assert lines[0]["slug"] == "x"
        assert "ts" in lines[0]
        assert lines[1]["event"] == "settle"
        assert lines[1]["pnl"] == 0.42

    def test_append_failure_does_not_raise(self, tmp_path):
        # Path that cannot be written (parent doesn't exist and is a file)
        bogus_parent = tmp_path / "afile"
        bogus_parent.write_text("blocking")
        bogus = str(bogus_parent / "child" / "trades.jsonl")
        # Should swallow the error rather than propagate
        trade_journal.append("submit", {"x": 1}, path=bogus)


# ---------------------------------------------------------------------------
# SniperBot helpers (preflight + settlement)
#
# We construct the bot with mocked client/state/feed/strategy, exercising the
# helpers directly.
# ---------------------------------------------------------------------------
def _make_bot(tmp_path, *, dry_run=False, trading_enabled=True,
              client_overrides: Optional[Dict[str, Any]] = None,
              state: Optional[BotState] = None):
    from bot_sniper import SniperBot
    from lib.sniper_strategy import SniperStrategy

    cfg = MagicMock()
    cfg.dry_run = dry_run
    cfg.trading_enabled = trading_enabled
    cfg.daily_loss_limit_usdc = 20
    cfg.consecutive_loss_limit = 3
    cfg.bet_size_usdc = 3.0

    client = MagicMock()
    overrides = client_overrides or {}
    for k, v in overrides.items():
        setattr(client, k, v)

    st = state or BotState()
    feed = MagicMock()
    strat = SniperStrategy(
        entry_secs=30, entry_window_low=25, entry_window_high=35,
        price_min=0.55, price_max=0.60, min_delta_bps=2.0,
        momentum_secs=30, kelly_fraction=0.5,
    )
    bot = SniperBot(config=cfg, client=client, state=st, feed=feed,
                    strategy=strat, market_ws=None)
    # redirect trade journal to a tmp file so no test pollutes the repo
    os.environ["TRADE_LOG_FILE"] = str(tmp_path / "trades.jsonl")
    return bot, client, st


class TestPreflightBalance:
    def test_dry_run_skips_check(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path, dry_run=True)
        ok, reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is True
        # Should NOT have queried the CLOB
        client.get_usdc_balance_allowance.assert_not_called()

    def test_trading_disabled_skips_check(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path, dry_run=False, trading_enabled=False)
        ok, _reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is True
        client.get_usdc_balance_allowance.assert_not_called()

    def test_blocks_when_balance_too_low(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path)
        client.get_usdc_balance_allowance.return_value = {
            "ok": True, "balance_usdc": 1.0, "allowance_usdc": 100.0, "raw": {},
        }
        ok, reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is False
        assert "余额" in reason

    def test_blocks_when_allowance_too_low(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path)
        client.get_usdc_balance_allowance.return_value = {
            "ok": True, "balance_usdc": 100.0, "allowance_usdc": 0.5, "raw": {},
        }
        ok, reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is False
        assert "approval" in reason

    def test_passes_when_sufficient(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path)
        client.get_usdc_balance_allowance.return_value = {
            "ok": True, "balance_usdc": 50.0, "allowance_usdc": 50.0, "raw": {},
        }
        ok, _reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is True

    def test_propagates_api_error_as_block(self, tmp_path):
        bot, client, _ = _make_bot(tmp_path)
        client.get_usdc_balance_allowance.return_value = {
            "ok": False, "error": "boom",
        }
        ok, reason, _ = bot._preflight_balance(notional_usdc=3.0)
        assert ok is False
        assert "boom" in reason


def _seed_pending(state: BotState, *, end_ts: int, **overrides) -> None:
    pe = {
        "slug": "btc-updown-5m-1700000000",
        "window_open_ts": end_ts - 300,
        "window_end_ts": end_ts,
        "direction": "UP",
        "token_id": "tok-up",
        "condition_id": "cond-1",
        "entry_price": 0.57,
        "shares_requested": 5.26,
        "notional_usdc": 3.0,
        "order_id": "ord-1",
        "submit_ts": end_ts - 30,
        "dry_run": False,
        "settled": False,
        "settle_attempts": 0,
    }
    pe.update(overrides)
    state.pending_entry = pe


class TestSettlement:
    def test_no_pending_no_op(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        st.pending_entry = None
        bot._settle_pending_entry(now=9999999999)
        client.get_btc_5m_market_by_slug.assert_not_called()

    def test_window_not_yet_ended_skips(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        _seed_pending(st, end_ts=2000000000)
        bot._settle_pending_entry(now=1999999000)  # before end
        client.get_btc_5m_market_by_slug.assert_not_called()
        assert st.pending_entry is not None  # still pending

    def test_unresolved_market_keeps_pending(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        _seed_pending(st, end_ts=1700000300)
        # gamma says market still open / outcomePrices missing
        client.get_btc_5m_market_by_slug.return_value = {
            "markets": [
                {"groupItemTitle": "UP", "closed": False, "outcomePrices": "[]"},
                {"groupItemTitle": "DOWN", "closed": False, "outcomePrices": "[]"},
            ],
        }
        client.get_open_orders.return_value = []
        client.get_trades_for_market.return_value = []
        bot._settle_pending_entry(now=1700000301)
        assert st.pending_entry is not None
        assert st.pending_entry["settle_attempts"] == 1

    def test_won_settles_with_positive_pnl(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        _seed_pending(st, end_ts=1700000300)
        # We bet UP; UP outcome resolved to "1"
        client.get_btc_5m_market_by_slug.return_value = {
            "markets": [
                {"groupItemTitle": "UP", "closed": True,
                 "outcomePrices": "[\"1\",\"0\"]"},
                {"groupItemTitle": "DOWN", "closed": True,
                 "outcomePrices": "[\"0\",\"1\"]"},
            ],
        }
        client.get_open_orders.return_value = []
        client.get_trades_for_market.return_value = [
            {"size": 5.26, "price": 0.57, "side": "BUY"},
        ]
        bot._settle_pending_entry(now=1700000400)
        assert st.pending_entry is None
        # PnL = 5.26 * (1 - 0.57) = 2.2618
        assert st.daily_trade_count == 1
        assert st.daily_pnl == pytest.approx(2.2618, rel=1e-3)
        assert st.consecutive_losses == 0
        # closed_positions captured
        assert len(st.closed_positions) == 1
        assert st.closed_positions[-1]["realized_pnl"] > 0

    def test_lost_settles_with_negative_pnl(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        _seed_pending(st, end_ts=1700000300, direction="UP")
        # UP lost
        client.get_btc_5m_market_by_slug.return_value = {
            "markets": [
                {"groupItemTitle": "UP", "closed": True,
                 "outcomePrices": "[\"0\",\"1\"]"},
                {"groupItemTitle": "DOWN", "closed": True,
                 "outcomePrices": "[\"1\",\"0\"]"},
            ],
        }
        client.get_open_orders.return_value = []
        client.get_trades_for_market.return_value = [
            {"size": 5.26, "price": 0.57, "side": "BUY"},
        ]
        bot._settle_pending_entry(now=1700000400)
        # PnL = 5.26 * (0 - 0.57) = -2.998
        assert st.daily_pnl == pytest.approx(-2.998, rel=1e-3)
        assert st.consecutive_losses == 1
        assert st.pending_entry is None

    def test_no_fill_records_no_trade_and_clears(self, tmp_path):
        bot, client, st = _make_bot(tmp_path)
        _seed_pending(st, end_ts=1700000300)
        client.get_btc_5m_market_by_slug.return_value = {
            "markets": [
                {"groupItemTitle": "UP", "closed": True,
                 "outcomePrices": "[\"1\",\"0\"]"},
                {"groupItemTitle": "DOWN", "closed": True,
                 "outcomePrices": "[\"0\",\"1\"]"},
            ],
        }
        # Order still open at window end → bot tries to cancel
        client.get_open_orders.return_value = [{"id": "ord-1"}]
        client.cancel_orders.return_value = {"canceled": ["ord-1"]}
        client.get_trades_for_market.return_value = []  # no fills
        bot._settle_pending_entry(now=1700000400)
        client.cancel_orders.assert_called_once_with(["ord-1"])
        # No fills → daily counters unchanged
        assert st.daily_trade_count == 0
        assert st.pending_entry is None  # but pending is cleared
