"""
Hedge formula toolkit for Polymarket binary markets.

Key formulas (fee rate f = 0.02 by default):

  Min hedge quantity:  Q_h = (P_m * Q_m) / ((1 - P_h) * (1 - f))
  Strategy viable:     (1 - P_m)(1 - P_h)(1 - f)^2 > P_m * P_h
  Profit if correct:   π₁ = Q_m*(1 - P_m)*(1 - f) - P_h*Q_h
  Loss if wrong:       π₀ = -(P_m*Q_m) + Q_h*(1 - P_h)*(1 - f)

Optimal entry ranges:
  Main position (P_m): 0.50 – 0.65
  Hedge position (P_h): 0.05 – 0.15
"""
import math
from typing import Dict, Any, Optional


FEE_RATE = 0.02  # Polymarket fee on winning positions


def min_hedge_quantity(
    main_price: float,
    main_qty: float,
    hedge_price: float,
    fee: float = FEE_RATE,
) -> float:
    """
    Minimum hedge quantity needed to break even on a loss.

    Q_h = (P_m * Q_m) / ((1 - P_h) * (1 - f))
    """
    denom = (1.0 - hedge_price) * (1.0 - fee)
    if denom <= 0:
        raise ValueError(f"Invalid hedge_price {hedge_price} or fee {fee}")
    return (main_price * main_qty) / denom


def is_strategy_viable(
    main_price: float,
    hedge_price: float,
    fee: float = FEE_RATE,
) -> bool:
    """
    Check the no-arbitrage viability condition.

    Viable when: (1 - P_m)(1 - P_h)(1 - f)^2 > P_m * P_h
    """
    lhs = (1.0 - main_price) * (1.0 - hedge_price) * (1.0 - fee) ** 2
    rhs = main_price * hedge_price
    return lhs > rhs


def profit_if_correct(
    main_price: float,
    main_qty: float,
    hedge_price: float,
    hedge_qty: float,
    fee: float = FEE_RATE,
) -> float:
    """
    Net profit when the main bet wins.

    π₁ = Q_m*(1 - P_m)*(1 - f) - P_h*Q_h
    """
    return main_qty * (1.0 - main_price) * (1.0 - fee) - hedge_price * hedge_qty


def loss_if_wrong(
    main_price: float,
    main_qty: float,
    hedge_price: float,
    hedge_qty: float,
    fee: float = FEE_RATE,
) -> float:
    """
    Net PnL when the main bet loses (hedge wins).

    π₀ = -P_m*Q_m + Q_h*(1 - P_h)*(1 - f)
    """
    return -main_price * main_qty + hedge_qty * (1.0 - hedge_price) * (1.0 - fee)


def kelly_optimal_hedge_ratio(
    win_prob: float,
    main_price: float,
    fee: float = FEE_RATE,
    r_min: float = 0.05,
    r_max: float = 0.50,
    steps: int = 46,
) -> float:
    """
    Grid-search Kelly-optimal hedge ratio r ∈ [r_min, r_max].

    r is the fraction of main notional allocated to the hedge.
    """
    best_r = r_min
    best_g = -math.inf
    for i in range(steps):
        r = r_min + i * (r_max - r_min) / max(steps - 1, 1)
        win_pnl = (1.0 - main_price) * (1.0 - fee) - r * main_price
        loss_pnl = -main_price + r * (1.0 - main_price) * (1.0 - fee)
        p = max(1e-9, min(1 - 1e-9, win_prob))
        if win_pnl <= -1 or loss_pnl <= -1:
            continue
        g = p * math.log(1 + win_pnl) + (1 - p) * math.log(1 + loss_pnl)
        if g > best_g:
            best_g, best_r = g, r
    return best_r


def scenario_summary(
    main_price: float,
    main_qty: float,
    hedge_price: float,
    hedge_qty: float,
    fee: float = FEE_RATE,
) -> Dict[str, Any]:
    """
    Full scenario summary dict for logging/display.
    """
    pi1 = profit_if_correct(main_price, main_qty, hedge_price, hedge_qty, fee)
    pi0 = loss_if_wrong(main_price, main_qty, hedge_price, hedge_qty, fee)
    viable = is_strategy_viable(main_price, hedge_price, fee)
    total_cost = main_price * main_qty + hedge_price * hedge_qty
    roi = pi1 / total_cost if total_cost > 0 else 0.0
    return {
        "main_price": main_price,
        "main_qty": main_qty,
        "hedge_price": hedge_price,
        "hedge_qty": hedge_qty,
        "fee_rate": fee,
        "total_cost": round(total_cost, 4),
        "profit_if_correct": round(pi1, 4),
        "loss_if_wrong": round(pi0, 4),
        "roi_pct": round(roi * 100, 2),
        "strategy_viable": viable,
    }
