"""
lib/hedge_formula.py — Precise Hedge Math with 2% Fee Model

All monetary quantities are in USDC (or whatever the collateral token is).
P_m  = main bet price  (probability the main outcome wins)
Q_m  = main bet quantity (USDC at risk)
P_h  = hedge bet price (probability the hedge outcome wins)
Q_h  = hedge bet quantity (USDC at risk)
fee  = Polymarket round-trip fee rate (default 2 %)
"""
from __future__ import annotations
import math
from typing import Dict

from lib.utils import log_info, log_warn

FEE_RATE: float = 0.02  # Polymarket 2% fee


def compute_min_hedge_quantity(
    P_m: float,
    Q_m: float,
    P_h: float,
    fee: float = FEE_RATE,
) -> float:
    """
    Minimum hedge quantity so that when the main bet *loses* we at least
    break even on the hedge payout.

    Derivation
    ----------
    When the main bet loses we receive the hedge payout:
        payout_h = Q_h * (1 - P_h) * (1 - fee)
    We need payout_h ≥ cost_m = P_m * Q_m

    Therefore:
        Q_h = (P_m * Q_m) / [(1 - P_h) * (1 - fee)]

    Parameters
    ----------
    P_m : float  Main position price (0 < P_m < 1)
    Q_m : float  Main position quantity (USDC)
    P_h : float  Hedge position price (0 < P_h < 1)
    fee : float  Fee rate (default 0.02)

    Returns
    -------
    float  Minimum hedge quantity in USDC
    """
    denominator = (1 - P_h) * (1 - fee)
    if denominator <= 0:
        log_warn("[HedgeFormula] compute_min_hedge_quantity: denominator <= 0, returning 0")
        return 0.0
    return (P_m * Q_m) / denominator


def check_strategy_feasibility(
    P_m: float,
    P_h: float,
    fee: float = FEE_RATE,
) -> Dict:
    """
    Check whether the strategy is mathematically profitable.

    Profitability condition (both scenarios must be positive):
        (1 - P_m)(1 - P_h)(1 - fee)^2 > P_m * P_h

    Returns
    -------
    dict with keys:
        feasible : bool
        margin   : float  (LHS - RHS; positive = profitable gap)
        details  : str
    """
    lhs = (1 - P_m) * (1 - P_h) * ((1 - fee) ** 2)
    rhs = P_m * P_h
    margin = lhs - rhs
    feasible = margin > 0
    details = (
        f"LHS={(1-P_m):.4f}×{(1-P_h):.4f}×{((1-fee)**2):.4f}={lhs:.6f}, "
        f"RHS={P_m:.4f}×{P_h:.4f}={rhs:.6f}, "
        f"margin={margin:+.6f}"
    )
    log_info(f"[HedgeFormula] feasibility: feasible={feasible} {details}")
    return {"feasible": feasible, "margin": margin, "details": details}


def compute_profit_scenarios(
    P_m: float,
    Q_m: float,
    P_h: float,
    Q_h: float,
    fee: float = FEE_RATE,
) -> Dict:
    """
    Calculate P&L for both binary outcomes.

    Scenario A — Main wins (main outcome resolves YES):
        Revenue  = Q_m * (1 - P_m) * (1 - fee)   [payout on main bet]
        Cost     = P_h * Q_h                        [cost of hedge bet]
        Profit_A = Revenue - Cost

    Scenario B — Hedge wins (hedge outcome resolves YES, i.e. main loses):
        Revenue  = Q_h * (1 - P_h) * (1 - fee)   [payout on hedge bet]
        Cost     = P_m * Q_m                        [cost of main bet]
        Profit_B = Revenue - Cost

    Returns
    -------
    dict with keys:
        main_wins_profit  : float
        hedge_wins_profit : float
        expected_value    : float   (average of the two, crude EV)
        max_loss          : float   (worst of the two, negative means loss)
    """
    profit_a = Q_m * (1 - P_m) * (1 - fee) - P_h * Q_h
    profit_b = Q_h * (1 - P_h) * (1 - fee) - P_m * Q_m
    ev = (profit_a + profit_b) / 2
    max_loss = min(profit_a, profit_b)
    log_info(
        f"[HedgeFormula] scenarios: main_wins={profit_a:.4f} "
        f"hedge_wins={profit_b:.4f} ev={ev:.4f} max_loss={max_loss:.4f}"
    )
    return {
        "main_wins_profit": profit_a,
        "hedge_wins_profit": profit_b,
        "expected_value": ev,
        "max_loss": max_loss,
    }


def optimal_hedge_with_kelly(
    P_m: float,
    Q_m: float,
    P_h: float,
    win_prob: float,
    fee: float = FEE_RATE,
) -> Dict:
    """
    Optimal hedge quantity combining the minimum break-even hedge with the
    Kelly criterion to scale exposure.

    Kelly fraction (simplified, single-bet form):
        b    = (1 - P_h) * (1 - fee) / P_h   [net odds in favour]
        f*   = (win_prob * b - (1 - win_prob)) / b
        f*   = max(0, f*)                       [no negative Kelly]

    We start from the minimum hedge Q_h_min and scale by f*:
        Q_h_kelly = Q_h_min * f*

    Parameters
    ----------
    P_m      : float  Main position price
    Q_m      : float  Main position quantity (USDC)
    P_h      : float  Hedge position price
    win_prob : float  Estimated probability that the hedge outcome wins
    fee      : float  Fee rate

    Returns
    -------
    dict with keys:
        hedge_quantity : float  Recommended hedge quantity in USDC
        hedge_cost     : float  P_h * hedge_quantity (actual USDC committed)
        kelly_fraction : float  Raw Kelly fraction before flooring
        min_hedge_qty  : float  Minimum hedge to break even
    """
    q_min = compute_min_hedge_quantity(P_m, Q_m, P_h, fee)

    # Net odds per unit risked on the hedge bet
    net_odds = (1 - P_h) * (1 - fee) / P_h if P_h > 0 else 0.0
    if net_odds <= 0:
        kelly_f = 0.0
    else:
        kelly_f = (win_prob * net_odds - (1 - win_prob)) / net_odds
        kelly_f = max(0.0, kelly_f)

    q_kelly = q_min * max(1.0, kelly_f)
    hedge_cost = P_h * q_kelly

    log_info(
        f"[HedgeFormula] kelly: f*={kelly_f:.4f} q_min={q_min:.4f} "
        f"q_kelly={q_kelly:.4f} hedge_cost={hedge_cost:.4f}"
    )
    return {
        "hedge_quantity": q_kelly,
        "hedge_cost": hedge_cost,
        "kelly_fraction": kelly_f,
        "min_hedge_qty": q_min,
    }
