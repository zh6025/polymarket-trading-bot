"""Unit tests for the market state machine."""
from __future__ import annotations

import time

import pytest

from polymarket.models import MarketInfo, Order, OrderStatus, Outcome, Side
from strategy.state_machine import MarketSession, MarketState


def make_market(secs_to_end: float = 300) -> MarketInfo:
    end_ts = time.time() + secs_to_end
    return MarketInfo(
        market_id="test-market-1",
        question="BTC Up or Down - 5 Minutes",
        token_id_up="token-up",
        token_id_down="token-down",
        end_date_iso="2026-03-13T13:00:00Z",
        end_timestamp=end_ts,
        active=True,
        slug="btc-updown-5m-test",
    )


def make_order(outcome: Outcome = Outcome.UP, price: float = 0.60) -> Order:
    return Order(
        order_id="ord-001",
        market_id="test-market-1",
        token_id="token-up",
        outcome=outcome,
        side=Side.BUY,
        price=price,
        size=1.0,
        status=OrderStatus.FILLED,
        filled_size=1.0,
        avg_fill_price=price,
        created_at=time.time(),
    )


class TestMarketSessionInit:
    def test_initial_state_is_observe(self):
        session = MarketSession(market=make_market())
        assert session.state == MarketState.OBSERVE

    def test_has_opportunity_slot_initially(self):
        session = MarketSession(market=make_market())
        assert session.has_opportunity_slot is True

    def test_total_entries_zero_initially(self):
        session = MarketSession(market=make_market())
        assert session.total_entries == 0


class TestMarketSessionTransitions:
    def test_observe_to_entered(self):
        session = MarketSession(market=make_market())
        session.transition(MarketState.ENTERED)
        assert session.state == MarketState.ENTERED

    def test_entered_to_opportunity(self):
        session = MarketSession(market=make_market())
        session.transition(MarketState.ENTERED)
        session.initial_order = make_order()
        session.opportunity_order = make_order(Outcome.DOWN, 0.15)
        session.transition(MarketState.OPPORTUNITY_BUY_DONE)
        assert session.state == MarketState.OPPORTUNITY_BUY_DONE

    def test_to_exited(self):
        session = MarketSession(market=make_market())
        session.transition(MarketState.ENTERED)
        session.transition(MarketState.EXITED)
        assert session.state == MarketState.EXITED


class TestMarketSessionProperties:
    def test_seconds_to_end(self):
        session = MarketSession(market=make_market(secs_to_end=120))
        assert 110 < session.seconds_to_end < 130

    def test_is_in_final_minute_false(self):
        session = MarketSession(market=make_market(secs_to_end=120))
        assert session.is_in_final_minute is False

    def test_is_in_final_minute_true(self):
        session = MarketSession(market=make_market(secs_to_end=30))
        assert session.is_in_final_minute is True

    def test_has_opportunity_slot_after_opp_placed(self):
        session = MarketSession(market=make_market())
        session.opportunity_order = make_order()
        assert session.has_opportunity_slot is False

    def test_total_entries_counts_both(self):
        session = MarketSession(market=make_market())
        session.initial_order = make_order()
        session.opportunity_order = make_order(Outcome.DOWN, 0.15)
        assert session.total_entries == 2
