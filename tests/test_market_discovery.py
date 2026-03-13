"""Unit tests for Gamma API market discovery helpers."""
from __future__ import annotations

import json
import time

import pytest

from polymarket.market_discovery import (
    _candidate_window_ends,
    _decode_json_field,
    _parse_event,
    _parse_standalone_market,
    BTC_5M_SLUG_FRAGMENT,
)


class TestDecodeJsonField:
    """Tests for the Gamma API JSON-string field decoder."""

    def test_plain_list_passthrough(self):
        assert _decode_json_field(["a", "b"]) == ["a", "b"]

    def test_json_encoded_string(self):
        assert _decode_json_field('["token1", "token2"]') == ["token1", "token2"]

    def test_none_returns_empty(self):
        assert _decode_json_field(None) == []

    def test_empty_string_returns_empty(self):
        assert _decode_json_field("") == []

    def test_single_value_string(self):
        """A bare non-JSON string is returned as a single-element list."""
        assert _decode_json_field("plain_token_id") == ["plain_token_id"]

    def test_invalid_json_string(self):
        """Invalid JSON strings are returned as a single-element list."""
        assert _decode_json_field("{not_json}") == ["{not_json}"]

    def test_json_encoded_with_whitespace(self):
        assert _decode_json_field('[ "a" , "b" ]') == ["a", "b"]

    def test_empty_list(self):
        assert _decode_json_field([]) == []

    def test_empty_json_array_string(self):
        assert _decode_json_field("[]") == []


class TestCandidateWindowEnds:
    """Tests for the 5-minute window timestamp derivation."""

    def test_current_window_included(self):
        """The current active window's end timestamp should be in the list."""
        now = 1773288000.0  # aligned to 5-min boundary
        ends = _candidate_window_ends(now)
        # Current window ends at now + 300
        assert (now + 300) in ends

    def test_all_multiples_of_300(self):
        now = 1773288100.0
        for ts in _candidate_window_ends(now):
            assert ts % 300 == 0, f"{ts} is not a 5-minute boundary"

    def test_covers_range(self):
        """Should return at least 3 candidate windows."""
        ends = _candidate_window_ends(time.time())
        assert len(ends) >= 3

    def test_reference_slug_timestamp(self):
        """The reference URL timestamp 1773288600 should be derivable."""
        # One second before the window ends
        now = 1773288600 - 1.0
        ends = _candidate_window_ends(now)
        assert 1773288600 in ends


class TestParseEvent:
    """Tests for _parse_event with realistic Gamma API response shapes."""

    def _make_event(
        self,
        slug="btc-updown-5m-1773288600",
        end_ts_offset=300,
        token_ids_format="list",   # "list" | "json_str"
        outcomes_format="list",    # "list" | "json_str"
        outcome_labels=("Yes", "No"),
    ) -> dict:
        now = time.time()
        end_ts = now + end_ts_offset
        from datetime import datetime, timezone
        end_iso = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        start_iso = datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()

        token_ids = ["token_up_123", "token_down_456"]
        if token_ids_format == "json_str":
            clob_ids = json.dumps(token_ids)
        else:
            clob_ids = token_ids

        if outcomes_format == "json_str":
            outcomes = json.dumps(list(outcome_labels))
        else:
            outcomes = list(outcome_labels)

        return {
            "slug": slug,
            "id": "event-001",
            "conditionId": "cond-001",
            "title": "BTC Up or Down - 5 Minutes",
            "startDate": start_iso,
            "endDate": end_iso,
            "active": True,
            "markets": [
                {
                    "id": "mkt-001",
                    "clobTokenIds": clob_ids,
                    "outcomes": outcomes,
                }
            ],
        }

    def test_parses_list_token_ids(self):
        event = self._make_event(token_ids_format="list")
        mi = _parse_event(event, time.time())
        assert mi is not None
        assert mi.token_id_up == "token_up_123"
        assert mi.token_id_down == "token_down_456"

    def test_parses_json_string_token_ids(self):
        """Gamma API returns clobTokenIds as a JSON-encoded string."""
        event = self._make_event(token_ids_format="json_str")
        mi = _parse_event(event, time.time())
        assert mi is not None
        assert mi.token_id_up == "token_up_123"
        assert mi.token_id_down == "token_down_456"

    def test_json_string_outcomes_used_for_ordering(self):
        """When outcomes are JSON strings the ordering is respected."""
        event = self._make_event(
            token_ids_format="json_str",
            outcomes_format="json_str",
            outcome_labels=("Yes", "No"),
        )
        mi = _parse_event(event, time.time())
        assert mi is not None
        assert mi.token_id_up == "token_up_123"
        assert mi.token_id_down == "token_down_456"

    def test_down_first_outcome_ordering(self):
        """If 'No'/'Down' is listed first, token ordering should be swapped."""
        event = self._make_event(
            token_ids_format="json_str",
            outcomes_format="json_str",
            outcome_labels=("No", "Yes"),
        )
        mi = _parse_event(event, time.time())
        assert mi is not None
        # "No" is at index 0 → DOWN, so UP is index 1
        assert mi.token_id_up == "token_down_456"   # second token
        assert mi.token_id_down == "token_up_123"   # first token

    def test_returns_none_for_wrong_slug(self):
        event = self._make_event(slug="some-other-market-123")
        mi = _parse_event(event, time.time())
        assert mi is None

    def test_returns_none_for_expired_market(self):
        event = self._make_event(end_ts_offset=-10)
        mi = _parse_event(event, time.time())
        assert mi is None

    def test_market_id_and_slug_populated(self):
        event = self._make_event()
        mi = _parse_event(event, time.time())
        assert mi is not None
        assert mi.slug == "btc-updown-5m-1773288600"
        assert mi.market_id == "cond-001"


class TestParseStandaloneMarket:
    """Tests for _parse_standalone_market."""

    def _make_market(self, token_ids_format="json_str") -> dict:
        now = time.time()
        from datetime import datetime, timezone
        end_iso = datetime.fromtimestamp(now + 300, tz=timezone.utc).isoformat()
        start_iso = datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()
        token_ids = ["tok_a", "tok_b"]
        clob_ids = json.dumps(token_ids) if token_ids_format == "json_str" else token_ids
        return {
            "conditionId": "cond-002",
            "slug": "btc-updown-5m-1773288600",
            "question": "BTC Up or Down - 5 Minutes",
            "startDate": start_iso,
            "endDate": end_iso,
            "active": True,
            "clobTokenIds": clob_ids,
            "outcomes": json.dumps(["Yes", "No"]),
        }

    def test_parses_json_string_token_ids(self):
        mkt = self._make_market(token_ids_format="json_str")
        mi = _parse_standalone_market(mkt, time.time())
        assert mi is not None
        assert mi.token_id_up in ("tok_a", "tok_b")
        assert mi.token_id_down in ("tok_a", "tok_b")
        assert mi.token_id_up != mi.token_id_down

    def test_parses_list_token_ids(self):
        mkt = self._make_market(token_ids_format="list")
        mi = _parse_standalone_market(mkt, time.time())
        assert mi is not None

    def test_returns_none_for_wrong_slug(self):
        mkt = self._make_market()
        mkt["slug"] = "some-other-market"
        mkt["question"] = "Something Else"
        mi = _parse_standalone_market(mkt, time.time())
        assert mi is None

    def test_returns_none_when_only_one_token_id(self):
        mkt = self._make_market()
        mkt["clobTokenIds"] = json.dumps(["only_one"])
        mi = _parse_standalone_market(mkt, time.time())
        assert mi is None
