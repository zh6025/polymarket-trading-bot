#!/usr/bin/env python3
"""scripts/preflight.py — 实盘前一键自检

跑这个脚本可以在不真正下单的前提下，确认实盘需要的所有前置条件：
  1. PRIVATE_KEY / FUNDER / SIGNATURE_TYPE 组合正确，能派生 API creds
  2. 钱包地址、Polymarket account 状态可读
  3. USDC 余额与 CLOB approval 充足

退出码：0=全部通过；2=自检失败（不要上实盘）。

Usage::

    # 本地或服务器都能直接跑
    TRADING_ENABLED=true DRY_RUN=true python3 scripts/preflight.py

注意：脚本不读取 TRADING_ENABLED/DRY_RUN，只要 PRIVATE_KEY 配好就会查询。
"""
from __future__ import annotations

import os
import sys

# 允许从仓库根目录直接 `python3 scripts/preflight.py` 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.config import Config  # noqa: E402
from lib.polymarket_client import PolymarketClient  # noqa: E402
from lib.utils import log_error, log_info, log_warn  # noqa: E402


def main() -> int:
    config = Config()
    log_info(
        f"配置: signature_type={config.signature_type} "
        f"funder={config.funder or '(空)'} chain_id={config.chain_id}"
    )
    if not config.private_key:
        log_error("❌ PRIVATE_KEY 未配置，无法做钱包自检；请先在 .env 中填好。")
        return 2

    client = PolymarketClient(
        host=config.clob_host,
        chain_id=config.chain_id,
        private_key=config.private_key,
        funder=config.funder or None,
        signature_type=config.signature_type,
        api_key=config.clob_api_key or None,
        api_secret=config.clob_api_secret or None,
        api_passphrase=config.clob_api_passphrase or None,
    )

    # 1) 钱包/签名/API creds 自检
    try:
        status = client.get_wallet_status()
    except Exception as e:
        log_error(f"❌ 无法初始化 CLOB 客户端: {e}")
        return 2
    log_info(f"🔐 钱包自检: {status}")
    if not status.get("ok"):
        log_error(
            "❌ 钱包/签名自检失败。常见原因："
            "  - SIGNATURE_TYPE 与 FUNDER 组合错误（0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE）"
            "  - FUNDER 填的是 EOA 地址而不是 Proxy/Safe 地址"
            "  - 该账户从未在 Polymarket 网站激活（先在网站上手动成交一次）"
        )
        return 2

    # 2) 余额与 approval
    bal = client.get_usdc_balance_allowance()
    if not bal.get("ok"):
        log_warn(f"⚠️  无法查询余额/授权: {bal.get('error')}")
        return 2
    log_info(
        f"💵 USDC 余额={bal['balance_usdc']:.2f} "
        f"approval={bal['allowance_usdc']:.2f}"
    )

    bet = config.bet_size_usdc
    threshold = bet * 1.05
    if bal["balance_usdc"] < threshold:
        log_error(
            f"❌ USDC 余额 {bal['balance_usdc']:.2f} < 单笔下注 {bet:.2f}（含5%缓冲），"
            f"请先充值后再上实盘。"
        )
        return 2
    if bal["allowance_usdc"] < threshold:
        log_error(
            f"❌ USDC approval {bal['allowance_usdc']:.2f} < 单笔下注 {bet:.2f}，"
            f"请到 Polymarket 网站完成 USDC approval（一次性操作）后再跑。"
        )
        return 2

    log_info("✅ 全部前置条件就绪，可以把 DRY_RUN=false 上实盘。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
