"""
SniperStrategy: 末端狙击策略核心
- 在窗口结束前25-35秒的时间窗评估入场信号
- 计算BTC相对于窗口开盘价的偏离(basis points)
- 检查最后30秒的动量方向是否与偏离方向一致
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


# BTC年化波动率（约65%），换算为每分钟：σ_1min = 0.65 / sqrt(365*24*60)
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
            window_open_price:  本窗口BTC开盘价
            current_btc_price:  BTC当前价格
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

        # Gate 2: BTC偏离检查
        if window_open_price <= 0:
            result['reasoning'] = "开盘价无效（<=0）"
            return result

        delta_bps = (current_btc_price - window_open_price) / window_open_price * 10_000
        if abs(delta_bps) < self.min_delta_bps:
            result['reasoning'] = (
                f"BTC偏离太小: {delta_bps:.2f} bps < {self.min_delta_bps} bps，接近随机"
            )
            return result

        primary_direction = 'UP' if delta_bps > 0 else 'DOWN'

        # Gate 3: 动量确认
        momentum_confirms = True
        momentum_str = "无动量数据"
        if momentum and momentum.get('n_samples', 0) >= 2:
            momentum_dir = momentum.get('direction', 'FLAT')
            if momentum_dir == 'FLAT':
                momentum_confirms = False
                momentum_str = f"动量平稳(FLAT)"
            elif momentum_dir == primary_direction:
                momentum_str = f"动量确认({momentum_dir}, {momentum.get('delta_bps', 0):.1f}bps)"
            else:
                momentum_confirms = False
                momentum_str = f"动量背离({momentum_dir} vs {primary_direction})"

        # 动量背离时大幅削减信号
        if not momentum_confirms:
            result['reasoning'] = f"动量背离，跳过: {momentum_str}"
            return result

        # Gate 4: 份额价格窗口
        if primary_direction == 'UP':
            entry_price = up_price
        else:
            entry_price = down_price

        if not (self.price_min <= entry_price <= self.price_max):
            result['reasoning'] = (
                f"份额价格{entry_price:.3f}不在窗口[{self.price_min}, {self.price_max}]"
            )
            return result

        # 概率估算：用布朗桥模型
        # 在T=5分钟窗口中，已经过了(300 - remaining_seconds)秒
        # P(UP) = Φ(delta / (σ√T_remaining))
        elapsed_minutes = (300 - remaining_seconds) / 60.0
        remaining_minutes = remaining_seconds / 60.0

        # 已走完的路径贡献到偏离
        btc_return = delta_bps / 10_000  # 转换为小数

        # 利用已知偏离推断最终方向的概率（布朗桥近似）
        vol_remaining = _VOL_PER_MIN * math.sqrt(remaining_minutes) if remaining_minutes > 0 else 1e-9
        z_score = btc_return / vol_remaining if vol_remaining > 0 else 0.0
        prob_up = _normal_cdf(z_score)

        if primary_direction == 'DOWN':
            estimated_prob = 1.0 - prob_up
        else:
            estimated_prob = prob_up

        # Gate 5: 期望值检查
        edge = estimated_prob - entry_price
        if edge <= 0:
            result['reasoning'] = (
                f"期望值为负: 估计概率={estimated_prob:.3f}, 份额价格={entry_price:.3f}, edge={edge:.3f}"
            )
            return result

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
            f"BTC偏离={delta_bps:.1f}bps | {momentum_str} | "
            f"估计概率={estimated_prob:.1%} | edge={edge:.3f} | "
            f"半Kelly={kelly_scaled:.3f} | 剩余={remaining_seconds}s"
        )
        return result
