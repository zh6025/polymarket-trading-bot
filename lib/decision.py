"""
交易决策层：顺序门控评估
1. 硬停（最后30秒不入场）
2. 最小剩余时间
3. 价格窗口（主仓 0.50-0.65，对冲 0.05-0.15）
4. Spread 检查
5. 深度检查
6. 信号评分检查
"""
import logging
from lib.hedge_formula import (
    check_strategy_feasibility,
    FEE_RATE
)

log = logging.getLogger(__name__)


def make_trade_decision(
    remaining_seconds: int,
    up_price: float,
    down_price: float,
    spread: float,
    depth: float,
    scorer_result: dict,
    # 配置参数
    hard_stop_sec: int = 30,
    min_secs_main: int = 90,
    min_secs_hedge: int = 60,
    main_price_min: float = 0.50,
    main_price_max: float = 0.65,
    hedge_price_min: float = 0.05,
    hedge_price_max: float = 0.15,
    max_spread: float = 0.05,
    min_depth: float = 50,
    min_confidence: float = 0.15,
    fee: float = FEE_RATE,
) -> dict:
    """
    返回 {
        'action': 'SKIP' | 'ENTER_MAIN_ONLY' | 'ENTER_MAIN_AND_HEDGE',
        'direction': 'UP' | 'DOWN' | None,
        'main_price': float,
        'hedge_price': float | None,
        'hedge_quantity': float | None,
        'reason': str,
    }
    """
    result = {
        'action': 'SKIP', 'direction': None,
        'main_price': 0, 'hedge_price': None,
        'hedge_quantity': None, 'reason': ''
    }

    # Gate 1: 硬停
    if remaining_seconds < hard_stop_sec:
        result['reason'] = f"硬停: 仅剩{remaining_seconds}s < {hard_stop_sec}s"
        return result

    # Gate 2: 最小时间
    if remaining_seconds < min_secs_main:
        result['reason'] = f"时间不足: {remaining_seconds}s < {min_secs_main}s"
        return result

    # Gate 3: 信号
    direction = scorer_result.get('direction', 'SKIP')
    if direction == 'SKIP':
        result['reason'] = f"信号不足: score={scorer_result.get('total_score', 0)}"
        return result

    confidence = abs(scorer_result.get('prob_up', 0.5) - 0.5) * 2
    if confidence < min_confidence:
        result['reason'] = f"置信度不足: {confidence:.2f} < {min_confidence}"
        return result

    # 确定方向和价格
    if direction == 'BUY_YES':
        main_price = up_price
        hedge_price = down_price
        bet_direction = 'UP'
    else:
        main_price = down_price
        hedge_price = up_price
        bet_direction = 'DOWN'

    # Gate 4: 主仓价格窗口
    if not (main_price_min <= main_price <= main_price_max):
        result['reason'] = f"主仓价格{main_price:.3f}超出窗口[{main_price_min}-{main_price_max}]"
        return result

    # Gate 5: Spread
    if spread > max_spread:
        result['reason'] = f"Spread过大: {spread:.4f} > {max_spread}"
        return result

    # Gate 6: 深度
    if depth < min_depth:
        result['reason'] = f"深度不足: {depth:.1f} < {min_depth}"
        return result

    result['direction'] = bet_direction
    result['main_price'] = main_price

    # Gate 7: 对冲可行性
    if hedge_price_min <= hedge_price <= hedge_price_max and remaining_seconds >= min_secs_hedge:
        feasibility = check_strategy_feasibility(main_price, hedge_price, fee)
        if feasibility['feasible']:
            result['action'] = 'ENTER_MAIN_AND_HEDGE'
            result['hedge_price'] = hedge_price
            result['reason'] = f"✅ 主仓+对冲: {bet_direction} @ {main_price:.3f}, 对冲 @ {hedge_price:.3f}"
            return result

    result['action'] = 'ENTER_MAIN_ONLY'
    result['reason'] = f"✅ 仅主仓: {bet_direction} @ {main_price:.3f} (对冲价{hedge_price:.3f}不在窗口)"
    return result
