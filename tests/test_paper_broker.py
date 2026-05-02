"""Tests for lib.paper_broker.simulate_limit_buy."""
from lib.paper_broker import simulate_limit_buy


def _book(asks):
    return {"asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def test_full_fill_single_level():
    res = simulate_limit_buy(_book([(0.55, 100)]), limit_price=0.55, size_shares=10)
    assert res["filled_shares"] == 10
    assert res["avg_fill_price"] == 0.55
    assert res["remaining_shares"] == 0
    assert res["fully_filled"] is True


def test_walks_book_ascending_when_asks_descending():
    # Polymarket /book returns asks 价格降序：best ask 在末尾
    res = simulate_limit_buy(_book([(0.60, 5), (0.58, 3), (0.55, 4)]),
                             limit_price=0.60, size_shares=10)
    # 应优先吃 0.55(4) → 0.58(3) → 0.60(3)
    assert res["filled_shares"] == 10
    expected_avg = (4 * 0.55 + 3 * 0.58 + 3 * 0.60) / 10
    assert abs(res["avg_fill_price"] - expected_avg) < 1e-6
    assert res["fully_filled"] is True


def test_partial_fill_when_limit_too_low():
    res = simulate_limit_buy(_book([(0.55, 4), (0.60, 10)]),
                             limit_price=0.55, size_shares=10)
    assert res["filled_shares"] == 4
    assert res["avg_fill_price"] == 0.55
    assert res["remaining_shares"] == 6
    assert res["fully_filled"] is False


def test_partial_fill_when_size_exceeds_book():
    res = simulate_limit_buy(_book([(0.55, 3)]), limit_price=0.60, size_shares=10)
    assert res["filled_shares"] == 3
    assert res["remaining_shares"] == 7
    assert res["fully_filled"] is False


def test_no_fill_when_all_above_limit():
    res = simulate_limit_buy(_book([(0.70, 10)]), limit_price=0.55, size_shares=5)
    assert res["filled_shares"] == 0
    assert res["avg_fill_price"] is None
    assert res["remaining_shares"] == 5
    assert res["fully_filled"] is False


def test_empty_or_missing_book():
    assert simulate_limit_buy({}, 0.55, 10)["filled_shares"] == 0
    assert simulate_limit_buy(None, 0.55, 10)["filled_shares"] == 0
    assert simulate_limit_buy({"asks": []}, 0.55, 10)["filled_shares"] == 0


def test_zero_or_negative_size():
    res = simulate_limit_buy(_book([(0.55, 10)]), 0.55, 0)
    assert res["filled_shares"] == 0
    assert res["fully_filled"] is True  # 没东西要买就算 "全成交"


def test_skips_malformed_levels():
    book = {"asks": [
        {"price": "0.55", "size": "5"},
        {"price": "bad", "size": "3"},
        {"price": "0.50", "size": "abc"},
        {"price": "0.52", "size": "2"},
    ]}
    res = simulate_limit_buy(book, 0.60, 10)
    # 只吃合法档位：0.52(2) → 0.55(5) = 7 股
    assert res["filled_shares"] == 7
    assert abs(res["avg_fill_price"] - (2 * 0.52 + 5 * 0.55) / 7) < 1e-6
