"""Paper-trading broker.

模拟限价单 BUY 的成交逻辑：在 Polymarket 真实订单簿（live order book）上做撮合，
但不真正下单。用于 DRY_RUN / 监管限制区域下复现实盘行为。

成交规则：
  * 输入限价 ``limit_price`` 与目标 ``size_shares``。
  * 把 asks 按价格升序遍历，吃掉所有 price <= limit_price 的档位，
    直到累计成交 = size_shares 或 ask 价格越过限价。
  * 返回 filled_shares / avg_fill_price / remaining_shares / fills 明细。

注：Polymarket /book 接口通常返回 asks 价格降序（best ask 在最后），
这里不假设输入顺序，统一在内部排序，调用方无需关心。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _coerce_levels(levels: Any) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    if not isinstance(levels, (list, tuple)):
        return out
    for lvl in levels:
        if not isinstance(lvl, dict):
            continue
        try:
            price = float(lvl.get("price"))
            size = float(lvl.get("size"))
        except (TypeError, ValueError):
            continue
        if size <= 0 or price < 0:
            continue
        out.append({"price": price, "size": size})
    return out


def simulate_limit_buy(
    book: Optional[Dict[str, Any]],
    limit_price: float,
    size_shares: float,
) -> Dict[str, Any]:
    """模拟一笔限价 BUY 单的成交。

    Args:
        book: ``PolymarketClient.get_orderbook`` 返回的 dict，含 ``asks`` 列表。
        limit_price: 限价（YES/NO 份额价格，0~1）。
        size_shares: 期望买入的股数。

    Returns:
        dict::

            {
              "filled_shares": float,     # 实际成交股数（可能 < size_shares）
              "avg_fill_price": float|None,  # 加权均价（无成交时 None）
              "remaining_shares": float,  # 未成交股数
              "fills": [{"price": float, "size": float}, ...],  # 各档成交明细
              "fully_filled": bool,
            }
    """
    target = max(float(size_shares), 0.0)
    lim = float(limit_price)
    if target <= 0 or lim <= 0:
        return {
            "filled_shares": 0.0,
            "avg_fill_price": None,
            "remaining_shares": target,
            "fills": [],
            "fully_filled": target == 0,
        }

    asks = _coerce_levels((book or {}).get("asks"))
    asks.sort(key=lambda lvl: lvl["price"])  # 升序：从最便宜的开始吃

    remaining = target
    filled = 0.0
    notional = 0.0
    fills: List[Dict[str, float]] = []
    # 价格比较保留 1e-9 的容差，避免浮点把 0.55 == 0.55 判成 >。
    eps = 1e-9
    for lvl in asks:
        if remaining <= eps:
            break
        if lvl["price"] > lim + eps:
            break
        take = min(remaining, lvl["size"])
        if take <= 0:
            continue
        filled += take
        notional += take * lvl["price"]
        fills.append({"price": lvl["price"], "size": round(take, 6)})
        remaining -= take

    avg = (notional / filled) if filled > 0 else None
    return {
        "filled_shares": round(filled, 6),
        "avg_fill_price": round(avg, 6) if avg is not None else None,
        "remaining_shares": round(max(remaining, 0.0), 6),
        "fills": fills,
        "fully_filled": remaining <= eps and filled > 0,
    }
