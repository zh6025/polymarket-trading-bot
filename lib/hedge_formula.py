"""
Polymarket 精确对冲数学公式（含2%手续费模型）

公式速查:
  最小对冲数量:   Q_h = (P_m * Q_m) / [(1 - P_h) * (1 - f)]
  策略可行条件:   (1-P_m)(1-P_h)(1-f)^2 > P_m * P_h
  正确时利润:     pi_1 = Q_m(1-P_m)(1-f) - P_h * Q_h

关键操作规则:
  - 对冲价越低越好: P_h 在 0.05~0.15 区间最佳
  - 主仓避免极端价格: P_m 在 0.50~0.65 之间效率最高
  - 先挂对冲单，对冲单成交后才下主仓
  - 手续费只对盈利收取（亏损不收）
"""
import math
import logging

log = logging.getLogger(__name__)

FEE_RATE = 0.02  # Polymarket 2% 手续费


def compute_min_hedge_quantity(P_m: float, Q_m: float, P_h: float,
                               fee: float = FEE_RATE) -> float:
    """
    最小对冲数量（判断错误时刚好保本）
    Q_h = (P_m * Q_m) / [(1 - P_h) * (1 - fee)]
    """
    denominator = (1 - P_h) * (1 - fee)
    if denominator <= 0:
        log.error(f"Invalid hedge params: P_h={P_h}, fee={fee}")
        return float('inf')
    return (P_m * Q_m) / denominator


def check_strategy_feasibility(P_m: float, P_h: float,
                                fee: float = FEE_RATE) -> dict:
    """
    检查策略是否数学上可行（正期望）
    条件: (1-P_m)(1-P_h)(1-fee)^2 > P_m * P_h
    """
    lhs = (1 - P_m) * (1 - P_h) * (1 - fee) ** 2
    rhs = P_m * P_h
    feasible = lhs > rhs
    margin = lhs - rhs

    # 计算最大可行对冲价
    # P_h_max = ((1-P_m)*(1-f)**2) / (P_m + (1-P_m)*(1-f)**2)
    numer = (1 - P_m) * (1 - fee) ** 2
    denom = P_m + numer
    max_hedge_price = numer / denom if denom > 0 else 0

    return {
        'feasible': feasible,
        'margin': round(margin, 6),
        'lhs': round(lhs, 6),
        'rhs': round(rhs, 6),
        'max_hedge_price': round(max_hedge_price, 4),
        'details': f"{'✅ 可行' if feasible else '❌ 不可行'}: "
                   f"(1-{P_m})(1-{P_h})(1-{fee})²={lhs:.6f} "
                   f"{'>' if feasible else '<='} "
                   f"{P_m}×{P_h}={rhs:.6f}"
    }


def compute_profit_scenarios(P_m: float, Q_m: float, P_h: float, Q_h: float,
                              fee: float = FEE_RATE) -> dict:
    """
    计算两种场景的利润/亏损：
    - 主仓正确(赢): profit = Q_m*(1-P_m)*(1-fee) - P_h*Q_h
    - 主仓错误(输，对冲赢): profit = Q_h*(1-P_h)*(1-fee) - P_m*Q_m
    """
    # 场景1: 主仓赢
    main_wins_profit = Q_m * (1 - P_m) * (1 - fee) - P_h * Q_h

    # 场景2: 对冲赢（主仓输）
    hedge_wins_profit = Q_h * (1 - P_h) * (1 - fee) - P_m * Q_m

    # 总成本
    total_cost = P_m * Q_m + P_h * Q_h

    # 最大亏损（两边都输，理论上Polymarket二元市场不会发生，但防御性计算）
    max_loss = total_cost

    return {
        'main_wins_profit': round(main_wins_profit, 4),
        'hedge_wins_profit': round(hedge_wins_profit, 4),
        'total_cost': round(total_cost, 4),
        'max_loss': round(max_loss, 4),
        'main_roi_pct': round(main_wins_profit / total_cost * 100, 2) if total_cost > 0 else 0,
        'hedge_roi_pct': round(hedge_wins_profit / total_cost * 100, 2) if total_cost > 0 else 0,
    }


def compute_optimal_hedge(P_m: float, Q_m: float, P_h: float,
                           win_prob: float = 0.55,
                           fee: float = FEE_RATE) -> dict:
    """
    计算最优对冲数量（考虑胜率）
    从最小对冲量开始，用 Kelly 公式调整。
    """
    Q_h_min = compute_min_hedge_quantity(P_m, Q_m, P_h, fee)
    feasibility = check_strategy_feasibility(P_m, P_h, fee)

    if not feasibility['feasible']:
        return {
            'hedge_quantity': 0,
            'hedge_cost': 0,
            'feasible': False,
            'reason': feasibility['details'],
        }

    # Kelly fraction for hedge sizing
    # b = (1-P_h)*(1-fee)/P_h - 1 (odds ratio for hedge bet)
    b = ((1 - P_h) * (1 - fee)) / P_h - 1 if P_h > 0 else 0
    q = 1 - win_prob  # probability of needing hedge
    kelly = (b * q - (1 - q)) / b if b > 0 else 0
    kelly = max(0, min(kelly, 0.5))  # cap at 50%

    # Scale hedge: at least min, scaled by kelly
    Q_h = max(Q_h_min, Q_h_min * (1 + kelly))
    hedge_cost = P_h * Q_h

    scenarios = compute_profit_scenarios(P_m, Q_m, P_h, Q_h, fee)

    return {
        'hedge_quantity': round(Q_h, 2),
        'hedge_cost': round(hedge_cost, 4),
        'min_hedge_quantity': round(Q_h_min, 2),
        'kelly_fraction': round(kelly, 4),
        'feasible': True,
        'scenarios': scenarios,
        'feasibility': feasibility,
    }
