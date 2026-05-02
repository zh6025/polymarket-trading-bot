"""
Tests for market-data parsing helpers in bot_sniper.py:
- _parse_outcome_prices: handles JSON strings / lists / bad inputs
- _parse_str_list: same shape but for string arrays (e.g. clobTokenIds, outcomes)
- _classify_up_down: robustly identifies UP/DOWN sub-markets across
  the various ways Polymarket's gamma API may shape the response.
"""
import pytest

from bot_sniper import (
    _classify_up_down,
    _extract_yes_price,
    _parse_outcome_prices,
    _parse_str_list,
)


# ---------------------------------------------------------------------------
# _parse_outcome_prices
# ---------------------------------------------------------------------------
class TestParseOutcomePrices:
    def test_list_of_floats(self):
        assert _parse_outcome_prices([0.52, 0.48]) == [0.52, 0.48]

    def test_list_of_strings(self):
        assert _parse_outcome_prices(["0.52", "0.48"]) == [0.52, 0.48]

    def test_json_string(self):
        assert _parse_outcome_prices('["0.52","0.48"]') == [0.52, 0.48]

    def test_none_returns_default(self):
        assert _parse_outcome_prices(None) == [0.5, 0.5]

    def test_invalid_json_returns_default(self):
        assert _parse_outcome_prices("not json") == [0.5, 0.5]

    def test_empty_list_returns_default(self):
        assert _parse_outcome_prices([]) == [0.5, 0.5]

    def test_unconvertible_returns_default(self):
        assert _parse_outcome_prices(["abc", "0.5"]) == [0.5, 0.5]

    def test_custom_default_empty(self):
        # Used by monitoring path so that "no data" stays distinguishable.
        assert _parse_outcome_prices(None, default=[]) == []
        assert _parse_outcome_prices("not json", default=[]) == []


# ---------------------------------------------------------------------------
# _parse_str_list
# ---------------------------------------------------------------------------
class TestParseStrList:
    def test_list(self):
        assert _parse_str_list(["a", "b"]) == ["a", "b"]

    def test_json_string(self):
        # gamma API returns clobTokenIds as a JSON-encoded string
        raw = '["12345678901234567890","98765432109876543210"]'
        assert _parse_str_list(raw) == [
            "12345678901234567890",
            "98765432109876543210",
        ]

    def test_none(self):
        assert _parse_str_list(None) == []

    def test_invalid_json(self):
        assert _parse_str_list("not json") == []

    def test_non_iterable(self):
        assert _parse_str_list(123) == []

    def test_coerces_to_str(self):
        assert _parse_str_list([1, 2]) == ["1", "2"]


# ---------------------------------------------------------------------------
# _classify_up_down
# ---------------------------------------------------------------------------
def _mkt(**kwargs):
    """Helper to build a minimal market dict."""
    return dict(kwargs)


class TestClassifyUpDown:
    def test_groupItemTitle_exact(self):
        up = _mkt(groupItemTitle="Up")
        down = _mkt(groupItemTitle="Down")
        u, d = _classify_up_down([up, down])
        assert u is up and d is down

    def test_groupItemTitle_reverse_order(self):
        up = _mkt(groupItemTitle="Up")
        down = _mkt(groupItemTitle="Down")
        u, d = _classify_up_down([down, up])
        assert u is up and d is down

    def test_question_keyword_when_groupItemTitle_missing(self):
        # Reproduces the live failure: groupItemTitle empty/missing — must
        # still classify by question text.
        up = _mkt(question="Will Bitcoin be UP between 10:30 and 10:35 AM ET?")
        down = _mkt(question="Will Bitcoin be DOWN between 10:30 and 10:35 AM ET?")
        u, d = _classify_up_down([up, down])
        assert u is up and d is down

    def test_slug_keyword(self):
        up = _mkt(slug="will-bitcoin-be-up-between-10-30-and-10-35")
        down = _mkt(slug="will-bitcoin-be-down-between-10-30-and-10-35")
        u, d = _classify_up_down([up, down])
        assert u is up and d is down

    def test_outcomes_field(self):
        # outcomes itself returned as JSON-string is also handled
        up = _mkt(outcomes='["Up","No"]')
        down = _mkt(outcomes='["Down","No"]')
        u, d = _classify_up_down([up, down])
        assert u is up and d is down

    def test_does_not_match_substring_updown(self):
        # Word-boundary regex must NOT classify "UPDOWN" as UP
        weird = _mkt(question="UPDOWN combined market")
        other = _mkt(question="Some other market")
        u, d = _classify_up_down([weird, other])
        # Falls back to positional since no clear UP/DOWN
        assert u is weird and d is other

    def test_event_level_up_or_down_phrase_does_not_confuse(self):
        # An event-level "Up or Down" phrase contains both words; it must
        # not be classified one-sided. Real UP/DOWN markets get matched.
        confuser = _mkt(question="Bitcoin Up or Down — May 1")
        up = _mkt(question="Will Bitcoin be UP at 10:35?")
        down = _mkt(question="Will Bitcoin be DOWN at 10:35?")
        u, d = _classify_up_down([confuser, up, down])
        assert u is up and d is down

    def test_positional_fallback_two_unknowns(self):
        a = _mkt(question="Market A")
        b = _mkt(question="Market B")
        u, d = _classify_up_down([a, b])
        assert u is a and d is b

    def test_partial_match_only_up(self):
        # Only UP can be identified; DOWN is filled by leftover positional
        up = _mkt(groupItemTitle="Up")
        other = _mkt(question="ambiguous")
        u, d = _classify_up_down([up, other])
        assert u is up and d is other

    def test_single_market(self):
        only = _mkt(groupItemTitle="Up")
        u, d = _classify_up_down([only])
        # UP found; DOWN has no leftover
        assert u is only and d is None

    def test_empty(self):
        assert _classify_up_down([]) == (None, None)


# ---------------------------------------------------------------------------
# _extract_yes_price — fallbacks when outcomePrices is missing
# ---------------------------------------------------------------------------
class TestExtractYesPrice:
    def test_uses_outcome_prices_first(self):
        m = {"outcomePrices": '["0.62","0.38"]', "lastTradePrice": "0.99"}
        assert _extract_yes_price(m) == 0.62

    def test_falls_back_to_last_trade_price(self):
        m = {"outcomePrices": None, "lastTradePrice": "0.55"}
        assert _extract_yes_price(m) == 0.55

    def test_falls_back_to_mid_of_bid_ask(self):
        m = {"bestBid": "0.40", "bestAsk": "0.50"}
        assert _extract_yes_price(m) == pytest.approx(0.45)

    def test_falls_back_to_single_side_bid(self):
        assert _extract_yes_price({"bestBid": "0.30"}) == 0.30

    def test_returns_none_when_all_missing(self):
        assert _extract_yes_price({}) is None
        assert _extract_yes_price(None) is None

    def test_ignores_empty_outcome_prices(self):
        # outcomePrices=[] should not block fallbacks
        m = {"outcomePrices": [], "lastTradePrice": "0.51"}
        assert _extract_yes_price(m) == 0.51
