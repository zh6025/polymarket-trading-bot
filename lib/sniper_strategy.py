"""
SniperStrategy: 末端狙击策略核心
- 在窗口结束前25-35秒的时间窗评估入场信号
- 直接基于Polymarket份额价格判断方向（哪个份额价格更高市场就预期那个方向）
- 只在份额价格 0.55-0.60 区间生成买入信号
- 使用半Kelly公式计算最优下注比例
- 返回 {action, direction, entry_price, edge, kelly_fraction, reasoning}
"""
import logging
import math
from typing import Optional

log = logging.getLogger(__name__)

try:
    from scipy.stats import norm as _norm
    def _normal_cdf(x: float) -> float:
        return float(_norm.cdf(x))
except ImportError:
    def _normal_cdf(x: float) -> float:
        """标准正态分布CDF近似（当scipy不可用时）"""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


_MIN_EDGE = 0.001  # 最小edge下限，保证有小额收益期望时仍允许入场
_ANNUAL_VOL = 0.65
_MINUTES_PER_YEAR = 365 * 24 * 60
_VOL_PER_MIN = _ANNUAL_VOL / math.sqrt(_MINUTES_PER_YEAR)


class SniperStrategy:
    """末端狙击策略"""

    def __init__(
        self,
        entry_secs: int = 30,
        entry_window_low: int = 25,
        entry_window_high: int = 35,
        price_min: float = 0.55,
        price_max: float = 0.60,
        min_delta_bps: float = 2.0,
        momentum_secs: int = 30,
        kelly_fraction: float = 0.5,
    ):
        """
        参数:
            entry_secs:         入场目标剩余秒数（中心值）
            entry_window_low:   入场窗口下限（剩余秒数）
            entry_window_high:  入场窗口上限（剩余秒数）
            price_min:          份额价格下限
            price_max:          份额价格上限
            min_delta_bps:      BTC最小偏离（基点）
            momentum_secs:      动量确认时间窗（秒）
            kelly_fraction:     Kelly系数缩放因子（0.5=半Kelly）
        """
        self.entry_secs = entry_secs
        self.entry_window_low = entry_window_low
        self.entry_window_high = entry_window_high
        self.price_min = price_min
        self.price_max = price_max
        self.min_delta_bps = min_delta_bps
        self.momentum_secs = momentum_secs
        self.kelly_fraction = kelly_fraction

    def evaluate(
        self,
        remaining_seconds: int,
        window_open_price: float,
        current_btc_price: float,
        up_price: float,
        down_price: float,
        momentum: Optional[dict] = None,
    ) -> dict:
        """
        评估是否入场，返回决策结果。

        参数:
            remaining_seconds:  距窗口结束的剩余秒数
            window_open_price:  本窗口BTC开盘价（保留API兼容，不再用于核心决策）
            current_btc_price:  BTC当前价格（保留API兼容，不再用于核心决策）
            up_price:           Polymarket UP份额当前价格
            down_price:         Polymarket DOWN份额当前价格
            momentum:           BinanceFeed.get_momentum()的结果（可选）

        返回:
            {
                'action': 'BUY_UP' | 'BUY_DOWN' | 'SKIP',
                'direction': 'UP' | 'DOWN' | None,
                'entry_price': float | None,
                'edge': float,
                'kelly_fraction': float,
                'estimated_prob': float,
                'reasoning': str,
            }
        """
        result = {
            'action': 'SKIP',
            'direction': None,
            'entry_price': None,
            'edge': 0.0,
            'kelly_fraction': 0.0,
            'estimated_prob': 0.5,
            'reasoning': '',
        }

        # Gate 1: 时间窗口检查
        if not (self.entry_window_low <= remaining_seconds <= self.entry_window_high):
            result['reasoning'] = (
                f"时间窗口不符: 剩余{remaining_seconds}s 不在 "
                f"[{self.entry_window_low}, {self.entry_window_high}]s"
            )
            return result

        # Gate 2: 直接用份额价格判断方向
        # 哪个份额价格更高，市场就认为那个方向更可能
        if up_price > down_price:
            primary_direction = 'UP'
            entry_price = up_price
            market_prob = up_price
        elif down_price > up_price:
            primary_direction = 'DOWN'
            entry_price = down_price
            market_prob = down_price
        else:
            result['reasoning'] = f"UP={up_price:.3f} DOWN={down_price:.3f} 完全均衡，无方向"
            return result

        # Gate 3: 份额价格必须在目标区间 [price_min, price_max]
        if not (self.price_min <= entry_price <= self.price_max):
            result['reasoning'] = (
                f"份额价格{entry_price:.3f}不在窗口[{self.price_min}, {self.price_max}]"
            )
            return result

        # Gate 4: 动量确认（可选，不作为硬性拒绝条件）
        momentum_str = "无动量数据"
        if momentum and momentum.get('n_samples', 0) >= 2:
            momentum_dir = momentum.get('direction', 'FLAT')
            momentum_bps = momentum.get('delta_bps', 0)
            if momentum_dir == primary_direction:
                momentum_str = f"动量确认({momentum_dir}, {momentum_bps:.1f}bps)"
            elif momentum_dir == 'FLAT':
                momentum_str = "动量平稳(FLAT)"
            else:
                momentum_str = f"动量背离({momentum_dir} vs {primary_direction})"

        # 概率估算：直接用份额价格作为市场隐含概率
        estimated_prob = market_prob

        # Edge计算：给一个小的时间衰减bonus（最后30秒翻转概率低）
        time_bonus = max(0.0, (35 - remaining_seconds) * 0.001)
        edge = estimated_prob - entry_price + time_bonus

        if edge <= 0:
            edge = _MIN_EDGE  # 给一个最小edge，允许入场

        # 半Kelly公式: f = kelly_fraction × (edge / (1 - entry_price))
        payout = 1.0 - entry_price  # 赢时每单位收益
        kelly_full = edge / payout if payout > 0 else 0.0
        kelly_scaled = self.kelly_fraction * kelly_full

        result['action'] = f'BUY_{primary_direction}'
        result['direction'] = primary_direction
        result['entry_price'] = entry_price
        result['edge'] = round(edge, 4)
        result['kelly_fraction'] = round(kelly_scaled, 4)
        result['estimated_prob'] = round(estimated_prob, 4)
        result['reasoning'] = (
            f"✅ 末端狙击: {primary_direction} @ {entry_price:.3f} | "
            f"市场概率={estimated_prob:.1%} | {momentum_str} | "
            f"edge={edge:.3f} | 半Kelly={kelly_scaled:.3f} | 剩余={remaining_seconds}s"
        )
        return result
