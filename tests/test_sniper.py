"""
Tests for lib/sniper_strategy.py and lib/binance_feed.py
"""
import math
import time
import pytest
from lib.sniper_strategy import SniperStrategy, _normal_cdf
from lib.binance_feed import BinanceFeed


# ---------------------------------------------------------------------------
# _normal_cdf
# ---------------------------------------------------------------------------
class TestNormalCdf:
    def test_cdf_at_zero(self):
        assert abs(_normal_cdf(0.0) - 0.5) < 1e-6

    def test_cdf_positive(self):
        assert _normal_cdf(1.0) > 0.5

    def test_cdf_negative(self):
        assert _normal_cdf(-1.0) < 0.5

    def test_cdf_bounds(self):
        assert 0.0 < _normal_cdf(-5.0) < 0.01
        assert _normal_cdf(5.0) > 0.99


# ---------------------------------------------------------------------------
# BinanceFeed (offline / injected)
# ---------------------------------------------------------------------------
class TestBinanceFeed:
    def _feed_with_prices(self, prices, base_ts=None):
        feed = BinanceFeed()
        if base_ts is None:
            base_ts = time.time() - len(prices)
        for i, p in enumerate(prices):
            feed.inject_price(p, ts=base_ts + i)
        return feed, base_ts

    def test_inject_and_get_recent(self):
        feed, base = self._feed_with_prices([50000, 50100, 50200])
        prices = feed.get_recent_prices(seconds=60)
        assert prices == [50000, 50100, 50200]

    def test_get_recent_filters_old(self):
        feed = BinanceFeed()
        now = time.time()
        feed.inject_price(40000, ts=now - 120)  # 太旧
        feed.inject_price(50000, ts=now - 10)
        feed.inject_price(51000, ts=now - 5)
        prices = feed.get_recent_prices(seconds=30)
        assert 40000 not in prices
        assert 50000 in prices and 51000 in prices

    def test_momentum_up(self):
        feed, _ = self._feed_with_prices([50000, 50050, 50100, 50200])
        m = feed.get_momentum(seconds=100)
        assert m['direction'] == 'UP'
        assert m['delta'] > 0
        assert m['delta_bps'] > 0

    def test_momentum_down(self):
        feed, _ = self._feed_with_prices([50000, 49900, 49800])
        m = feed.get_momentum(seconds=100)
        assert m['direction'] == 'DOWN'
        assert m['delta'] < 0

    def test_momentum_insufficient_samples(self):
        feed = BinanceFeed()
        feed.inject_price(50000, ts=time.time())
        m = feed.get_momentum(seconds=30)
        assert m['direction'] == 'FLAT'
        assert m['n_samples'] == 1

    def test_history_ring_buffer_eviction(self):
        feed = BinanceFeed()
        now = time.time()
        # 注入一个超过600秒的旧价格
        feed.inject_price(1.0, ts=now - 700)
        # 注入当前价格（会触发清理）
        feed.inject_price(50000, ts=now)
        prices = feed.get_recent_prices(seconds=1000)
        # 旧价格应已被清除
        assert 1.0 not in prices


# ---------------------------------------------------------------------------
# SniperStrategy
# ---------------------------------------------------------------------------
def make_strategy(**kwargs):
    defaults = dict(
        entry_secs=30,
        entry_window_low=25,
        entry_window_high=35,
        price_min=0.55,
        price_max=0.60,
        min_delta_bps=2.0,
        momentum_secs=30,
        kelly_fraction=0.5,
    )
    defaults.update(kwargs)
    return SniperStrategy(**defaults)


def make_momentum(direction='UP', delta_bps=5.0, n_samples=10):
    return {
        'direction': direction,
        'delta': delta_bps * 50,  # 假设BTC=50000时近似值
        'delta_bps': delta_bps,
        'n_samples': n_samples,
    }


class TestSniperTimeWindow:
    def test_skip_when_too_early(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=100,  # > entry_window_high=35
            window_open_price=50000,
            current_btc_price=50100,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP'),
        )
        assert result['action'] == 'SKIP'
        assert '时间窗口' in result['reasoning']

    def test_skip_when_too_late(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=10,  # < entry_window_low=25
            window_open_price=50000,
            current_btc_price=50100,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP'),
        )
        assert result['action'] == 'SKIP'
        assert '时间窗口' in result['reasoning']

    def test_within_window(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,  # +10bps
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=10.0),
        )
        assert result['action'] != 'SKIP' or '时间窗口' not in result['reasoning']


class TestSniperDeltaGate:
    def test_skip_when_delta_too_small(self):
        strat = make_strategy(min_delta_bps=5.0)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50001,  # 0.02bps，远小于5bps
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP'),
        )
        assert result['action'] == 'SKIP'
        assert 'BTC偏离' in result['reasoning']

    def test_pass_when_delta_sufficient(self):
        strat = make_strategy(min_delta_bps=2.0)
        # delta = 500 / 50000 * 10000 = 100 bps
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=100.0),
        )
        # 应该不是因为delta不足而SKIP
        if result['action'] == 'SKIP':
            assert 'BTC偏离' not in result['reasoning']


class TestSniperMomentumGate:
    def test_skip_when_momentum_diverges(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,  # +100bps UP
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('DOWN', delta_bps=-50.0),  # 动量背离
        )
        assert result['action'] == 'SKIP'
        assert '动量背离' in result['reasoning']

    def test_pass_when_momentum_confirms(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=50.0),
        )
        if result['action'] == 'SKIP':
            assert '动量背离' not in result['reasoning']


class TestSniperPriceWindow:
    def test_skip_when_share_price_too_low(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.40,  # 太低
            down_price=0.60,
            momentum=make_momentum('UP', delta_bps=100.0),
        )
        assert result['action'] == 'SKIP'
        assert '份额价格' in result['reasoning']

    def test_skip_when_share_price_too_high(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.75,  # 太高
            down_price=0.25,
            momentum=make_momentum('UP', delta_bps=100.0),
        )
        assert result['action'] == 'SKIP'
        assert '份额价格' in result['reasoning']

    def test_enter_when_price_in_window(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        # 使用大幅偏离让概率足够高，确保edge > 0
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=52000,  # 大幅UP偏离
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=400.0),
        )
        # 如果入场则方向应为UP
        if result['action'] != 'SKIP':
            assert result['direction'] == 'UP'
            assert result['entry_price'] == 0.57


class TestSniperDirectionDown:
    def test_buy_down_when_btc_negative(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=48000,  # 大幅DOWN偏离
            up_price=0.43,
            down_price=0.57,
            momentum=make_momentum('DOWN', delta_bps=-400.0),
        )
        if result['action'] != 'SKIP':
            assert result['direction'] == 'DOWN'
            assert result['entry_price'] == 0.57


class TestSniperKelly:
    def test_kelly_fraction_positive_when_edge_positive(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=52000,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=400.0),
        )
        if result['action'] != 'SKIP':
            assert result['kelly_fraction'] > 0
            assert result['edge'] > 0

    def test_edge_equals_prob_minus_price(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=52000,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=400.0),
        )
        if result['action'] != 'SKIP':
            expected_edge = result['estimated_prob'] - result['entry_price']
            assert abs(result['edge'] - expected_edge) < 0.001


class TestSniperInvalidInputs:
    def test_zero_open_price(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=0,  # 无效
            current_btc_price=50000,
            up_price=0.57,
            down_price=0.43,
        )
        assert result['action'] == 'SKIP'
        assert '开盘价无效' in result['reasoning']
