import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────
MIN_PROFIT_RATE = 0.02      # 最低套利利润率 2%（合计 < 0.98 才进场）
ORDER_SIZE      = 5.0       # 每次下单USDC金额
POLL_INTERVAL   = 5         # 轮询间隔（秒）
MIN_USDC        = 20.0      # USDC余额低于此值停止交易
# ──────────────────────────────────────────────

HOST     = "https://clob.polymarket.com"
CHAIN_ID = 137

client = ClobClient(
    HOST,
    key=os.getenv("PK"),
    chain_id=CHAIN_ID,
    signature_type=1,
    funder=os.getenv("FUNDER"),
)
client.set_api_creds(ApiCreds(
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
    api_passphrase=os.getenv("API_PASSPHRASE"),
))
logger.info("ClobClient initialized LIVE")

# ── 统计 ──────────────────────────────────────
stats = {
    "cycles": 0,
    "arb_found": 0,
    "orders_placed": 0,
    "orders_failed": 0,
    "total_profit_est": 0.0,
}

def get_usdc_balance():
    try:
        p = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=1)
        return int(client.get_balance_allowance(p)["balance"]) / 1e6
    except Exception as e:
        logger.error(f"余额查询失败: {e}")
        return 0.0

def get_orderbook_best(token_id):
    """获取最优ask价格（我们以ask价买入）"""
    try:
        book = client.get_order_book(token_id)
        asks = book.asks  # 卖单列表
        if not asks:
            return None
        # 最低ask = 我们能买到的最便宜价格
        best_ask = min(float(a.price) for a in asks)
        return best_ask
    except Exception as e:
        logger.error(f"orderbook获取失败 {token_id[:16]}: {e}")
        return None

def find_active_market():
    """找当前活跃的BTC 5分钟市场"""
    import requests, json, time as t
    now = int(t.time())
    # 找最近的5分钟时间槽
    slot = (now // 300) * 300
    for offset in [0, 300, -300]:
        ts = slot + offset
        slug = f"btc-updown-5m-{ts}"
        try:
            url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
            resp = requests.get(url, timeout=5).json()
            if not resp:
                continue
            m = resp[0] if isinstance(resp, list) else resp
            if not m.get("acceptingOrders", False):
                continue
            raw = m.get("clobTokenIds", "[]")
            token_ids = json.loads(raw) if isinstance(raw, str) else raw
            if len(token_ids) < 2:
                continue
            logger.info(f"找到市场: {m.get('question','?')}")
            return token_ids[0], token_ids[1]  # UP, DOWN
        except Exception as e:
            logger.warning(f"slug={slug} 查询失败: {e}")
    return None, None

def place_buy(token_id, price, size, label):
    """市价买入（以ask价挂GTC单）"""
    try:
        signed = client.create_order(OrderArgs(
            token_id=token_id,
            price=round(price, 4),
            size=round(size, 2),
            side=BUY,
        ))
        resp = client.post_order(signed, OrderType.GTC)
        oid = resp.get("orderID", "?")
        status = resp.get("status", "?")
        logger.info(f"[{label}] BUY {size:.2f}shares @ {price:.4f} → {status} id={oid[:16]}")
        stats["orders_placed"] += 1
        return True
    except Exception as e:
        logger.error(f"[{label}] BUY失败 @ {price:.4f}: {e}")
        stats["orders_failed"] += 1
        return False

# ── 主循环 ────────────────────────────────────
logger.info("=== 套利机器人启动 ===")
logger.info(f"最低利润率: {MIN_PROFIT_RATE*100:.1f}% | 单次规模: ${ORDER_SIZE} | 轮询: {POLL_INTERVAL}s")

last_market = (None, None)
last_arb_ts = 0  # 防止同一市场重复下单

while True:
    try:
        stats["cycles"] += 1

        # 1. 检查余额
        usdc = get_usdc_balance()
        if usdc < MIN_USDC:
            logger.warning(f"USDC余额不足 ${usdc:.2f} < ${MIN_USDC}，暂停")
            time.sleep(30)
            continue

        # 2. 找市场
        up_id, down_id = find_active_market()
        if not up_id:
            logger.warning("未找到活跃市场，等待...")
            time.sleep(POLL_INTERVAL)
            continue

        # 3. 获取最优买价
        up_ask   = get_orderbook_best(up_id)
        down_ask = get_orderbook_best(down_id)

        if up_ask is None or down_ask is None:
            logger.warning(f"orderbook不完整 UP={up_ask} DOWN={down_ask}")
            time.sleep(POLL_INTERVAL)
            continue

        total = up_ask + down_ask
        profit_rate = 1.0 - total
        market_key = f"{up_id[:8]}_{down_id[:8]}"

        logger.info(
            f"[Cycle {stats['cycles']}] UP={up_ask:.4f} DOWN={down_ask:.4f} "
            f"合计={total:.4f} 利润率={profit_rate*100:.2f}% USDC=${usdc:.2f}"
        )

        # 4. 套利条件判断
        if profit_rate >= MIN_PROFIT_RATE:
            # 防止同一市场同一分钟重复下单
            now_ts = int(time.time())
            if market_key == f"{last_market[0]}_{last_market[1]}" and now_ts - last_arb_ts < 60:
                logger.info("同一市场60秒内已下单，跳过")
                time.sleep(POLL_INTERVAL)
                continue

            logger.info(f"🎯 套利机会！利润率={profit_rate*100:.2f}% 合计={total:.4f}")
            stats["arb_found"] += 1

            # 按比例分配资金
            up_size   = round(ORDER_SIZE / up_ask,   2)
            down_size = round(ORDER_SIZE / down_ask, 2)

            logger.info(f"下单: UP {up_size:.2f}shares @ {up_ask:.4f} + DOWN {down_size:.2f}shares @ {down_ask:.4f}")
            logger.info(f"预计成本: ${ORDER_SIZE*2:.2f} | 预计收益: ${(up_size+down_size)*profit_rate:.4f}")

            ok1 = place_buy(up_id,   up_ask,   up_size,   "UP")
            ok2 = place_buy(down_id, down_ask, down_size, "DOWN")

            if ok1 and ok2:
                est_profit = (up_size + down_size) * profit_rate
                stats["total_profit_est"] += est_profit
                last_arb_ts = now_ts
                last_market = (up_id[:8], down_id[:8])
                logger.info(f"✅ 套利完成！预计利润 ${est_profit:.4f} | 累计预计 ${stats['total_profit_est']:.4f}")
            else:
                logger.error("❌ 部分订单失败，检查持仓！")

        # 5. 打印统计
        if stats["cycles"] % 12 == 0:  # 每分钟
            logger.info(
                f"=== 统计 cycles={stats['cycles']} arb={stats['arb_found']} "
                f"orders={stats['orders_placed']} failed={stats['orders_failed']} "
                f"est_profit=${stats['total_profit_est']:.4f} ==="
            )

        time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("手动停止")
        break
    except Exception as e:
        logger.error(f"主循环错误: {e}")
        time.sleep(POLL_INTERVAL)

logger.info(f"=== 最终统计: {stats} ===")
