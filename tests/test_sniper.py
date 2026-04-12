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
        )
        assert result['action'] == 'SKIP'
        assert '时间窗口' in result['reasoning']

    def test_within_window(self):
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.57,
            down_price=0.43,
        )
        assert result['action'] != 'SKIP' or '时间窗口' not in result['reasoning']


class TestSniperDeltaGate:
    def test_btc_delta_ignored_direction_from_share_prices(self):
        """BTC偏离不再决定方向，方向由份额价格决定"""
        strat = make_strategy(min_delta_bps=5.0)
        # BTC几乎没动（旧逻辑会SKIP），但UP份额>DOWN份额，应该触发BUY_UP
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50001,  # 仅0.02bps偏离，旧逻辑会拒绝
            up_price=0.57,
            down_price=0.43,
        )
        # 新逻辑：不应因为BTC偏离小而SKIP
        assert 'BTC偏离' not in result['reasoning']

    def test_direction_comes_from_share_price(self):
        """方向由份额价格高低决定，与BTC涨跌无关"""
        strat = make_strategy(min_delta_bps=2.0)
        # BTC大幅上涨，但DOWN份额更高 → 应该买DOWN
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,  # BTC涨了
            up_price=0.43,
            down_price=0.57,  # 但市场认为DOWN更可能
        )
        if result['action'] != 'SKIP':
            assert result['direction'] == 'DOWN'
            assert result['entry_price'] == 0.57


class TestSniperMomentumGate:
    def test_no_skip_when_momentum_diverges(self):
        """动量背离不再硬性拒绝，只在reasoning中记录"""
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.57,  # UP份额更高 → 方向为UP
            down_price=0.43,
            momentum=make_momentum('DOWN', delta_bps=-50.0),  # 动量背离
        )
        # 新逻辑：动量背离不导致SKIP
        assert result['action'] == 'BUY_UP'
        assert '动量背离' in result['reasoning']

    def test_momentum_confirmation_noted_in_reasoning(self):
        """动量确认时在reasoning中标注"""
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.57,
            down_price=0.43,
            momentum=make_momentum('UP', delta_bps=50.0),
        )
        if result['action'] != 'SKIP':
            assert '动量背离' not in result['reasoning']


class TestSniperPriceWindow:
    def test_skip_when_share_price_too_low(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        # 两个份额价格都太低（都在0.5附近），最高的也不在[0.55, 0.60]区间
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50500,
            up_price=0.52,  # 稍高但低于price_min=0.55
            down_price=0.48,
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
        )
        assert result['action'] == 'SKIP'
        assert '份额价格' in result['reasoning']

    def test_enter_when_price_in_window(self):
        strat = make_strategy(price_min=0.55, price_max=0.60)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=52000,
            up_price=0.57,
            down_price=0.43,
        )
        assert result['action'] == 'BUY_UP'
        assert result['direction'] == 'UP'
        assert result['entry_price'] == 0.57


class TestSniperDirectionDown:
    def test_buy_down_when_down_price_higher(self):
        """DOWN份额价格更高时，买DOWN"""
        strat = make_strategy(price_min=0.55, price_max=0.60)
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=48000,
            up_price=0.43,
            down_price=0.57,  # DOWN份额更高
        )
        assert result['action'] == 'BUY_DOWN'
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
        )
        assert result['action'] == 'BUY_UP'
        assert result['kelly_fraction'] > 0
        assert result['edge'] > 0

    def test_edge_at_least_time_bonus(self):
        """edge = estimated_prob - entry_price + time_bonus
        When entry_price == estimated_prob (share price is both), edge = time_bonus.
        For remaining_seconds=30: time_bonus = (35-30)*0.001 = 0.005"""
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=52000,
            up_price=0.57,
            down_price=0.43,
        )
        assert result['action'] == 'BUY_UP'
        # estimated_prob == entry_price == 0.57, so edge = 0 + time_bonus = 0.005
        assert result['edge'] >= 0.005


class TestSniperInvalidInputs:
    def test_equal_up_down_prices_skips(self):
        """UP和DOWN完全相等时无方向，应SKIP"""
        strat = make_strategy()
        result = strat.evaluate(
            remaining_seconds=30,
            window_open_price=50000,
            current_btc_price=50000,
            up_price=0.50,
            down_price=0.50,
        )
        assert result['action'] == 'SKIP'
        assert '均衡' in result['reasoning']
