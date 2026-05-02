"""
Tests for ``lib/polymarket_ws.py`` — the Polymarket CLOB market WebSocket
client.

These tests focus on the **message parsing / cache** logic, not the
network layer.  We feed pre-parsed dicts into ``_handle_message`` and check
that ``get_mid`` / ``get_book_summary`` reflect the latest snapshot.
"""
import time

import pytest

from lib.polymarket_ws import (
    PolymarketMarketWS,
    _BookState,
    _coerce_float,
    _parse_levels,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ws_with(tokens):
    ws = PolymarketMarketWS(freshness_sec=60.0)
    # Bypass the real network — directly mark these tokens as the active set
    # so that ``_book_for`` accepts incoming messages.
    ws._active_tokens = {str(t) for t in tokens}
    return ws


# ---------------------------------------------------------------------------
# _coerce_float / _parse_levels
# ---------------------------------------------------------------------------
class TestCoerceFloat:
    def test_basic(self):
        assert _coerce_float("0.5") == 0.5
        assert _coerce_float(0.5) == 0.5
        assert _coerce_float(1) == 1.0

    def test_invalid(self):
        assert _coerce_float(None) is None
        assert _coerce_float("") is None
        assert _coerce_float("abc") is None


class TestParseLevels:
    def test_dict_levels(self):
        levels = [{"price": "0.5", "size": "100"}, {"price": "0.49", "size": "50"}]
        assert _parse_levels(levels) == [(0.5, 100.0), (0.49, 50.0)]

    def test_skips_invalid(self):
        levels = [{"price": "0.5"}, {"size": "100"}, {"price": "x", "size": "1"},
                  {"price": "0.4", "size": "10"}]
        assert _parse_levels(levels) == [(0.4, 10.0)]

    def test_non_list(self):
        assert _parse_levels(None) == []
        assert _parse_levels("foo") == []


# ---------------------------------------------------------------------------
# _BookState
# ---------------------------------------------------------------------------
class TestBookState:
    def test_snapshot_sorts_and_drops_zero(self):
        b = _BookState("tok")
        b.apply_snapshot([(0.40, 10), (0.45, 5), (0.42, 0)],
                         [(0.55, 8), (0.50, 12), (0.52, 0)])
        assert b.bids == [(0.45, 5), (0.40, 10)]
        assert b.asks == [(0.50, 12), (0.55, 8)]
        assert b.best_bid() == 0.45
        assert b.best_ask() == 0.50
        assert b.mid() == pytest.approx(0.475)

    def test_mid_single_side(self):
        b = _BookState("tok")
        b.apply_snapshot([(0.40, 10)], [])
        assert b.mid() == 0.40
        b2 = _BookState("tok")
        b2.apply_snapshot([], [(0.55, 1)])
        assert b2.mid() == 0.55

    def test_empty_book_mid_none(self):
        b = _BookState("tok")
        assert b.mid() is None

    def test_apply_change_buy_then_delete(self):
        b = _BookState("tok")
        b.apply_snapshot([(0.40, 10)], [(0.55, 8)])
        # add a higher bid
        b.apply_change(0.45, 5, "BUY")
        assert b.best_bid() == 0.45
        # update existing bid in place (replace size)
        b.apply_change(0.45, 7, "BUY")
        assert b.bids[0] == (0.45, 7)
        # size 0 deletes
        b.apply_change(0.45, 0, "BUY")
        assert b.best_bid() == 0.40

    def test_apply_change_sell(self):
        b = _BookState("tok")
        b.apply_snapshot([(0.40, 10)], [(0.55, 8)])
        b.apply_change(0.50, 3, "SELL")
        assert b.best_ask() == 0.50
        # 'ask' alias also accepted
        b.apply_change(0.49, 2, "ask")
        assert b.best_ask() == 0.49

    def test_apply_change_unknown_side_ignored(self):
        b = _BookState("tok")
        b.apply_snapshot([(0.40, 10)], [(0.55, 8)])
        before = (list(b.bids), list(b.asks))
        b.apply_change(0.50, 3, "MAYBE")
        assert (b.bids, b.asks) == before

    def test_freshness(self):
        b = _BookState("tok")
        assert b.is_fresh(10.0) is False  # never updated
        b.apply_snapshot([(0.40, 10)], [(0.55, 8)])
        assert b.is_fresh(10.0) is True
        # simulate stale by hand
        b.last_update_ts = time.monotonic() - 100.0
        assert b.is_fresh(10.0) is False


# ---------------------------------------------------------------------------
# PolymarketMarketWS message dispatch
# ---------------------------------------------------------------------------
class TestDispatch:
    def test_book_snapshot_dict(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message({
            "event_type": "book",
            "asset_id": "TOK1",
            "bids": [{"price": "0.45", "size": "10"}],
            "asks": [{"price": "0.55", "size": "20"}],
        })
        assert ws.get_mid("TOK1") == pytest.approx(0.50)

    def test_book_snapshot_list(self):
        # Initial WSS connect responds with a list of book dicts.
        ws = _ws_with(["TOK1", "TOK2"])
        payload = [
            {"asset_id": "TOK1",
             "bids": [{"price": "0.40", "size": "5"}],
             "asks": [{"price": "0.50", "size": "5"}]},
            {"asset_id": "TOK2",
             "bids": [{"price": "0.30", "size": "5"}],
             "asks": [{"price": "0.32", "size": "5"}]},
        ]
        ws._handle_message(payload)
        assert ws.get_mid("TOK1") == pytest.approx(0.45)
        assert ws.get_mid("TOK2") == pytest.approx(0.31)

    def test_json_string_input(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message(
            '{"asset_id":"TOK1","bids":[{"price":"0.6","size":"1"}],'
            '"asks":[{"price":"0.7","size":"1"}]}'
        )
        assert ws.get_mid("TOK1") == pytest.approx(0.65)

    def test_bytes_input(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message(
            b'{"asset_id":"TOK1","bids":[{"price":"0.6","size":"1"}],'
            b'"asks":[{"price":"0.7","size":"1"}]}'
        )
        assert ws.get_mid("TOK1") == pytest.approx(0.65)

    def test_invalid_json_does_not_raise(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message("not json")
        assert ws.get_mid("TOK1") is None

    def test_pong_ignored(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message("PONG")
        assert ws.get_mid("TOK1") is None

    def test_unsubscribed_token_ignored(self):
        ws = _ws_with(["TOK1"])
        # TOK_OTHER is NOT in the active set — must NOT be cached
        ws._handle_message({
            "asset_id": "TOK_OTHER",
            "bids": [{"price": "0.1", "size": "1"}],
            "asks": [{"price": "0.2", "size": "1"}],
        })
        assert ws.get_mid("TOK_OTHER") is None
        assert "TOK_OTHER" not in ws._books

    def test_price_change_increment(self):
        ws = _ws_with(["TOK1"])
        # seed snapshot
        ws._handle_message({
            "asset_id": "TOK1",
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.55", "size": "10"}],
        })
        # incremental: a better bid arrives (top-level asset_id form)
        ws._handle_message({
            "event_type": "price_change",
            "asset_id": "TOK1",
            "price_changes": [
                {"price": "0.50", "size": "5", "side": "BUY"},
            ],
        })
        assert ws.get_mid("TOK1") == pytest.approx(0.525)

    def test_price_change_per_change_asset_id(self):
        ws = _ws_with(["TOK1"])
        ws._handle_message({
            "asset_id": "TOK1",
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.55", "size": "10"}],
        })
        # Some servers nest asset_id inside each change instead of top-level
        ws._handle_message({
            "changes": [
                {"asset_id": "TOK1", "price": "0.52", "size": "3", "side": "SELL"},
            ],
        })
        assert ws.get_mid("TOK1") == pytest.approx(0.46)


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------
class TestSetActiveTokens:
    def test_replacing_drops_old_books(self):
        ws = _ws_with([])
        ws.set_active_tokens(["TOK1", "TOK2"])
        # Pretend we received a book for TOK1
        ws._handle_message({
            "asset_id": "TOK1",
            "bids": [{"price": "0.4", "size": "1"}],
            "asks": [{"price": "0.5", "size": "1"}],
        })
        assert ws.get_mid("TOK1") is not None
        # Window rolls over — different tokens
        ws.set_active_tokens(["TOK3"])
        # Old book is gone (no stale data)
        assert ws.get_mid("TOK1") is None
        assert "TOK1" not in ws._books
        assert ws._active_tokens == {"TOK3"}

    def test_idempotent(self):
        ws = _ws_with([])
        ws.set_active_tokens(["A", "B"])
        ws._reconnect_event.clear()
        ws.set_active_tokens(["B", "A"])  # same set, different order
        # No new reconnect triggered
        assert not ws._reconnect_event.is_set()
