#!/usr/bin/env python3
import os, time, logging, requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs, ApiCreds
from py_clob_client.order_builder.constants import BUY, SELL

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

AMOUNT = 3.0
MIN_PRICE = 0.30
MAX_PRICE = 0.75
TP_PCT = 0.25
SL_PCT = 0.25
DAILY_LOSS_LIMIT = 20.0

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
_tg_offset = 0
_bot_running = True

def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass

def tg_check_commands():
    global _tg_offset, _bot_running
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params={"offset": _tg_offset, "timeout": 1},
            timeout=5,
        )
        for upd in r.json().get("result", []):
            _tg_offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = msg.get("text", "").strip().lower()
            cid = str(msg.get("chat", {}).get("id", ""))
            if cid != str(TG_CHAT_ID):
                continue
            if text == "/stop":
                _bot_running = False
                tg("🛑 Bot已停止！")
                log.info("[TG] 收到/stop")
            elif text == "/start":
                _bot_running = True
                tg("▶️ Bot已启动！")
                log.info("[TG] 收到/start")
            elif text == "/status":
                tg(f"状态: {'✅运行中' if _bot_running else '🛑已停止'}")
            elif text == "/help":
                tg("/stop /start /status /help")
    except Exception:
        pass

def get_btc_trend():
    def closes(limit):
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": limit},
                timeout=10,
            )
            return [float(c[4]) for c in r.json()]
        except Exception as e:
            log.warning(f"BTC K线失败: {e}")
            return []

    def trend(cs):
        if len(cs) < 3:
            return None, "数据不足"
        pct = (cs[-1] - cs[0]) / cs[0] * 100
        if pct > 0.03:
            return "UP", f"+{pct:.2f}%"
        elif pct < -0.03:
            return "DOWN", f"{pct:.2f}%"
        return None, f"横盘{pct:.2f}%"

    c1h  = closes(60)
    c15m = closes(15)
    c5m  = closes(5)

    t1h,  d1h  = trend(c1h)
    t15m, d15m = trend(c15m)
    t5m,  d5m  = trend(c5m)

    log.info(f"BTC趋势 1h={t1h}({d1h}) 15m={t15m}({d15m}) 5m={t5m}({d5m})")

    if t1h == t15m == t5m and t1h is not None:
        return t1h, 3, f"1h{d1h} 15m{d15m} 5m{d5m} 三框架一致"
    if t1h == t15m and t1h is not None:
        return t1h, 2, f"1h{d1h} 15m{d15m} 两框架一致"
    return None, 0, f"趋势不一致 1h={t1h} 15m={t15m} 5m={t5m}"

def get_slug_and_end():
    now = int(time.time())
    base_ts = (now // 300) * 300
    end_ts = base_ts + 300
    slug = f"btc-updown-5m-{base_ts}"
    return slug, base_ts, end_ts

def get_market_tokens(slug):
    try:
        import json
        r = requests.get(
            f"https://gamma-api.polymarket.com/markets?slug={slug}",
            timeout=10
        )
        markets = r.json()
        if not markets:
            return None, None
        tokens = markets[0].get("clobTokenIds") or markets[0].get("tokens", [])
        if isinstance(tokens, str):
            tokens = json.loads(tokens)
        if len(tokens) < 2:
            return None, None
        def tid(t):
            return t if isinstance(t, str) else t.get("token_id", "")
        return tid(tokens[0]), tid(tokens[1])
    except Exception as e:
        log.warning(f"get_market_tokens失败: {e}")
        return None, None

def get_mid_price(client, token_id):
    try:
        book = client.get_order_book(token_id)
        bids = book.bids or []
        asks = book.asks or []
        bp = float(bids[0].price) if bids else 0.0
        ap = float(asks[0].price) if asks else 1.0
        return round((bp + ap) / 2, 4)
    except:
        return 0.5

def get_usdc(client):
    try:
        r = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        return round(float(r.get("balance", 0)) / 1e6, 2)
    except:
        return 0.0

def place_order(client, token_id, side, price, amount, label):
    try:
        size = round(amount / price, 2) if price > 0 else amount
        size = max(size, round(1.0 / price + 0.01, 2))
        size = max(size, 5.0)
        o = client.create_and_post_order(OrderArgs(
            token_id=token_id,
            price=round(price, 2),
            size=size,
            side=side,
        ))
        cost = round(size * price, 2)
        log.info(f"✅ [{label}] {side} price={price:.3f} size={size} 成本=${cost}")
        tg(f"✅ <b>[{label}]</b> {side} price={price:.3f} size={size} 成本=${cost}")
        return o
    except Exception as e:
        log.error(f"❌ [{label}] 下单失败: {e}")
        tg(f"❌ <b>[{label}]</b> 下单失败: {e}")
        return None

class Position:
    def __init__(self, direction, token_id, entry_price, size, label):
        self.direction = direction
        self.token_id = token_id
        self.entry_price = entry_price
        self.size = size
        self.label = label

    def cur_price(self, up_p, down_p):
        return up_p if self.direction == "UP" else down_p

    def pnl(self, up_p, down_p):
        cp = self.cur_price(up_p, down_p)
        return (cp - self.entry_price) / self.entry_price

def run():
    log.info("🚀 Bot v2 启动 - BTC多时间框架趋势策略")
    tg("🚀 <b>Bot v2 启动</b>\n策略: BTC 1h/15m/5m趋势\n入场: 30%~75%\n单次: $3")

    client = ClobClient(
        os.getenv("HOST", "https://clob.polymarket.com"),
        key=os.getenv("PK"),
        chain_id=int(os.getenv("CHAIN_ID", "137")),
        signature_type=1,
        funder=os.getenv("FUNDER"),
    )
    client.set_api_creds(ApiCreds(
        api_key=os.getenv("API_KEY"),
        api_secret=os.getenv("API_SECRET"),
        api_passphrase=os.getenv("API_PASSPHRASE"),
    ))

    positions = []
    last_slug = None
    traded = False
    daily_loss = 0.0
    stats = dict(cycles=0, entries=0, tp=0, sl=0, pnl=0.0)

    while True:
        try:
            tg_check_commands()
            slug, base_ts, end_ts = get_slug_and_end()
            now = int(time.time())
            remain = end_ts - now

            if slug != last_slug:
                stats["cycles"] += 1
                usdc = get_usdc(client)
                log.info(f"══ 新周期: {slug} 剩余{remain}s USDC=${usdc} ══")
                tg(f"🔄 新周期 剩余{remain}s | USDC=${usdc:.1f} | 持仓={len(positions)}")
                last_slug = slug
                traded = False

            up_tid, down_tid = get_market_tokens(slug)
            if not up_tid or not down_tid:
                time.sleep(5)
                continue

            up_p = get_mid_price(client, up_tid)
            down_p = get_mid_price(client, down_tid)
            usdc = get_usdc(client)

            log.info(f"[C{stats['cycles']}] UP={up_p:.4f} DOWN={down_p:.4f} 剩余={remain}s USDC=${usdc} 持仓={len(positions)}")

            if daily_loss >= DAILY_LOSS_LIMIT:
                log.warning(f"日亏损${daily_loss:.2f}达上限，停止")
                time.sleep(5)
                continue

            closed = []
            for pos in positions:
                pnl = pos.pnl(up_p, down_p)
                cp = pos.cur_price(up_p, down_p)
                if pnl >= TP_PCT:
                    log.info(f"🎯 止盈 [{pos.label}] +{pnl*100:.1f}%")
                    tg(f"🎯 止盈 <b>[{pos.label}]</b> +{pnl*100:.1f}%")
                    place_order(client, pos.token_id, SELL, cp, pos.size, f"{pos.label}-TP")
                    stats["tp"] += 1
                    stats["pnl"] += pos.size * pnl
                    closed.append(pos)
                elif pnl <= -SL_PCT:
                    log.info(f"🛑 止损 [{pos.label}] {pnl*100:.1f}%")
                    tg(f"🛑 止损 <b>[{pos.label}]</b> {pnl*100:.1f}%")
                    place_order(client, pos.token_id, SELL, cp, pos.size, f"{pos.label}-SL")
                    loss = pos.size * abs(pnl)
                    stats["sl"] += 1
                    stats["pnl"] -= loss
                    daily_loss += loss
                    closed.append(pos)
            for p in closed:
                positions.remove(p)

            if not _bot_running:
                log.info("[TG] Bot已停止，跳过交易")
            elif not traded and 30 < remain < 270:
                direction, strength, desc = get_btc_trend()
                if strength >= 2:
                    if direction == "UP" and MIN_PRICE <= up_p <= MAX_PRICE:
                        log.info(f"📈 买UP 强度={strength} 价={up_p:.3f} | {desc}")
                        if place_order(client, up_tid, BUY, up_p, AMOUNT, "UP"):
                            positions.append(Position("UP", up_tid, up_p, AMOUNT, "UP"))
                            stats["entries"] += 1
                            traded = True
                    elif direction == "DOWN" and MIN_PRICE <= down_p <= MAX_PRICE:
                        log.info(f"📉 买DOWN 强度={strength} 价={down_p:.3f} | {desc}")
                        if place_order(client, down_tid, BUY, down_p, AMOUNT, "DOWN"):
                            positions.append(Position("DOWN", down_tid, down_p, AMOUNT, "DOWN"))
                            stats["entries"] += 1
                            traded = True
                    else:
                        log.info(f"⏭ 价格不在范围 UP={up_p:.3f} DOWN={down_p:.3f}")
                else:
                    log.info(f"⏭ 信号弱(强度={strength}): {desc}")

            time.sleep(5)

        except KeyboardInterrupt:
            log.info("Bot停止")
            tg("⛔ Bot已手动停止")
            break
        except Exception as e:
            log.error(f"主循环异常: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run()
