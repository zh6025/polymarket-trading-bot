import time
import os
import requests
import logging
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, ApiCreds, ApiCreds
from py_clob_client.order_builder.constants import BUY, SELL
from web3 import Web3

# ─── 日志 ────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/smart_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── 配置 ────────────────────────────────────────────────────
HOST     = os.getenv("HOST", "https://clob.polymarket.com")
KEY      = os.getenv("PK", "")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))

AMOUNT_S1 = 2.0
AMOUNT_S2 = 2.0
AMOUNT_S3 = 2.0
TP_PCT    = 0.30
SL_PCT    = 0.30
DAILY_LOSS_LIMIT = 30.0

# 策略1：趋势跟随
S1_MID_LOW  = 0.35   # 中位区间
S1_MID_HIGH = 0.65
# 策略2：极端价格
S2_ENTRY   = 0.25
S2_MIN_SEC = 120
# 策略3：结尾追趋势
S3_THRESHOLD = 0.70
S3_WIN_LOW   = 10
S3_WIN_HIGH  = 120

GAMMA_URL = "https://gamma-api.polymarket.com"

# ─── CTF Approval ────────────────────────────────────────────
CTF_ADDRESS   = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
EXCHANGE_ADDR = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
CTF_ABI = [
    {"inputs":[{"name":"operator","type":"address"},{"name":"approved","type":"bool"}],
     "name":"setApprovalForAll","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"operator","type":"address"}],
     "name":"isApprovedForAll","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"}
]

def check_ctf():
    for rpc in ["https://polygon-bor-rpc.publicnode.com","https://rpc.ankr.com/polygon","https://polygon.llamarpc.com"]:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc))
            if not w3.is_connected(): continue
            acct = w3.eth.account.from_key(KEY)
            ctf  = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
            if ctf.functions.isApprovedForAll(acct.address, Web3.to_checksum_address(EXCHANGE_ADDR)).call():
                log.info("CTF setApprovalForAll 已设置 ✅")
                return True
            log.warning("CTF未设置（需要MATIC充gas才能提前卖出）")
            return False
        except Exception as e:
            log.warning(f"CTF检查({rpc}): {e}")
    return False

# ─── 市场工具 ─────────────────────────────────────────────────
def get_slug_and_end(offset_periods=0):
    """offset_periods=0当前, -1上一个, -2上上个"""
    now_ts  = int(time.time())
    base_ts = (now_ts // 300) * 300 + offset_periods * 300
    end_ts  = base_ts + 300
    return f"btc-updown-5m-{base_ts}", base_ts, end_ts

def get_market_tokens(slug):
    """返回(up_token_id, down_token_id) 或 (None,None)"""
    try:
        r = requests.get(f"{GAMMA_URL}/markets", params={"slug": slug}, timeout=10)
        ms = r.json()
        if not ms: return None, None
        m = ms[0] if isinstance(ms, list) else ms
        tokens = m.get("tokens", m.get("clobTokenIds", []))
        if isinstance(tokens, str):
            import json; tokens = json.loads(tokens)
        if len(tokens) < 2: return None, None
        def tid(t):
            if isinstance(t, dict):
                return t.get("token_id") or t.get("tokenId") or ""
            return str(t)
        return tid(tokens[0]), tid(tokens[1])
    except Exception as e:
        log.warning(f"get_market_tokens({slug}): {e}")
        return None, None

def get_final_price(token_id):
    """获取某个已结算token的最终价格（接近0或1）"""
    try:
        r = requests.get(
            "https://clob.polymarket.com/prices-history",
            params={"market": token_id, "interval": "all", "fidelity": 1},
            timeout=10
        )
        history = r.json().get("history", [])
        if not history: return None
        return float(history[-1]["p"])
    except:
        return None

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


# ── Telegram通知 ──────────────────────────────────────
TG_TOKEN   = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

def tg(msg: str):
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


# ── Telegram命令控制 ──────────────────────────────────────
_tg_offset = 0
_bot_running = True

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
        data = r.json()
        for upd in data.get("result", []):
            _tg_offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = msg.get("text", "").strip().lower()
            cid  = str(msg.get("chat", {}).get("id", ""))
            if cid != str(TG_CHAT_ID):
                continue
            if text == "/stop":
                _bot_running = False
                tg("🛑 Bot已停止！不再开新仓。")
                log.info("[TG] 收到/stop指令")
            elif text == "/start":
                _bot_running = True
                tg("▶️ Bot已启动！恢复交易。")
                log.info("[TG] 收到/start指令")
            elif text == "/status":
                tg(f"📊 状态: {'✅运行中' if _bot_running else '🛑已停止'}")
            elif text == "/help":
                tg("📋 命令列表:
/stop - 停止交易
/start - 恢复交易
/status - 查看状态
/help - 帮助")
    except Exception:
        pass

def place_order(client, token_id, side, price, amount, label):
    try:
        # size = 购买的份数，成本 = size * price >= 1美元
        # amount是我们愿意花的USDC，size = amount / price
        size = round(amount / price, 2) if price > 0 else round(amount, 2)
        size = max(size, round(1.0 / price + 0.01, 2))  # 保证成本>=1美元
        size = max(size, 5.0)  # 最小size=5股
        o = client.create_and_post_order(OrderArgs(
            token_id=token_id,
            price=round(price, 2),
            size=size,
            side=side,
        ))
        cost = round(size * price, 2)
        log.info(f"✅ [{label}] side={side} price={price:.3f} size={size} 成本=${cost}")
        tg(f"✅ <b>[{label}]</b> {side} price={price:.3f} size={size} 成本=${cost}")
        return o
    except Exception as e:
        log.error(f"❌ [{label}] 下单失败: {e}")
        tg(f"❌ <b>[{label}]</b> 下单失败: {e}")
        return None

# ─── 跨���期趋势分析 ───────────────────────────────────────────
class CycleTrend:
    """
    记录过去各个5分钟周期的结果：
      UP赢  → +1
      DOWN赢 → -1
    通过累计判断趋势方向
    """
    def __init__(self):
        # {base_ts: +1/-1/None}
        self.results = {}

    def update(self, client):
        """扫描过去3个周期，记录结果"""
        for offset in [-1, -2, -3]:
            slug, base_ts, end_ts = get_slug_and_end(offset)
            if base_ts in self.results:
                continue  # 已记录
            now_ts = int(time.time())
            if now_ts < end_ts + 10:
                continue  # 还没结算完
            up_tid, down_tid = get_market_tokens(slug)
            if not up_tid:
                continue
            up_final = get_final_price(up_tid)
            if up_final is None:
                continue
            if up_final > 0.5:
                self.results[base_ts] = +1
                log.info(f"📊 历史周期 {slug}: UP赢 (final={up_final:.3f})")
            else:
                self.results[base_ts] = -1
                log.info(f"📊 历史周期 {slug}: DOWN赢 (final={up_final:.3f})")

    def analyze(self):
        """
        返回(方向, 连续数, 描述)
        看最近3个周期的结果
        """
        now_ts  = int(time.time())
        base_ts = (now_ts // 300) * 300
        # 取最近3个已结算周期
        recent_keys = sorted(
            [k for k in self.results if k < base_ts],
            reverse=True
        )[:3]

        if not recent_keys:
            return None, 0, "无历史数据"

        vals = [self.results[k] for k in recent_keys]
        desc_parts = []
        for i, k in enumerate(recent_keys):
            ago = (base_ts - k) // 300
            w = "UP赢" if self.results[k] == +1 else "DOWN赢"
            desc_parts.append(f"{ago}期前:{w}")
        desc = " | ".join(desc_parts)

        up_count   = vals.count(+1)
        down_count = vals.count(-1)

        # 5分钟前（最近一期）
        last = vals[0] if vals else 0
        # 15分钟趋势（3期一致）
        if up_count == 3:
            return "UP", 3, desc
        elif down_count == 3:
            return "DOWN", 3, desc
        # 2/3一致也算
        elif up_count >= 2:
            return "UP", 2, desc
        elif down_count >= 2:
            return "DOWN", 2, desc
        # 只看最近1期
        elif last == +1:
            return "UP", 1, desc
        elif last == -1:
            return "DOWN", 1, desc
        return None, 0, desc

# ─── 持仓 ────────────────────────────────────────────────────
class Position:
    def __init__(self, strategy, direction, token_id, entry_price, size, label):
        self.strategy    = strategy
        self.direction   = direction
        self.token_id    = token_id
        self.entry_price = entry_price
        self.size        = size
        self.label       = label

    def cur_price(self, up_p, down_p):
        return up_p if self.direction == "UP" else down_p

    def pnl(self, up_p, down_p):
        cp = self.cur_price(up_p, down_p)
        return (cp - self.entry_price) / self.entry_price

# ─── 主循环 ──────────────────────────────────────────────────
def run():
    log.info("═══════════════════════════════════════════════════")
    log.info("  多策略机器人 v3（跨周期趋势）")
    log.info(f"  S1 趋势跟随: 看前5m/15m周期结果 买中位${AMOUNT_S1}")
    log.info(f"  S2 极端价格: <{S2_ENTRY} 买${AMOUNT_S2} 距结算>{S2_MIN_SEC}s")
    log.info(f"  S3 结尾追趋势: >{S3_THRESHOLD} 最后{S3_WIN_HIGH}s 买${AMOUNT_S3}")
    log.info(f"  止盈+{int(TP_PCT*100)}% 止损-{int(SL_PCT*100)}% 日上限${DAILY_LOSS_LIMIT}")
    log.info("═══════════════════════════════════════════════════")

    client = ClobClient(
        HOST,
        key=KEY,
        chain_id=CHAIN_ID,
        signature_type=1,
        funder=os.getenv("FUNDER"),
    )
    client.set_api_creds(ApiCreds(
        api_key=os.getenv("API_KEY"),
        api_secret=os.getenv("API_SECRET"),
        api_passphrase=os.getenv("API_PASSPHRASE"),
    ))
    log.info(f"客户端初始化完成 ✅ KEY={KEY[:6]}... API={os.getenv('API_KEY','')[:8]}...")
    check_ctf()

    trend      = CycleTrend()
    positions  = []
    daily_loss = 0.0
    stats      = dict(cycles=0, entries=0, tp=0, sl=0, pnl=0.0)
    s1_done = s2_done = s3_done = False
    last_slug = ""

    try:
        while True:
            stats["cycles"] += 1
            now_ts = int(time.time())
            slug, base_ts, end_ts = get_slug_and_end(0)
            remain = end_ts - now_ts

            # 新周期
            if slug != last_slug:
                log.info(f"══ 新周期: {slug} 剩余{remain}s ══")
                s1_done = s2_done = s3_done = False
                last_slug = slug

            # 更新历史周期结果
            trend.update(client)

            # 获取当前市场
            up_tid, down_tid = get_market_tokens(slug)
            if not up_tid or not down_tid:
                log.warning(f"市场token获取失败: {slug}")
                time.sleep(5)
                continue

            usdc = get_usdc(client)
            up_p   = get_mid_price(client, up_tid)
            down_p = get_mid_price(client, down_tid)

            log.info(f"[Cycle {stats['cycles']}] UP={up_p:.4f} DOWN={down_p:.4f} "
                     f"剩余={remain}s USDC=${usdc} 持仓={len(positions)}")

            if daily_loss >= DAILY_LOSS_LIMIT:
                log.warning(f"日亏损${daily_loss:.2f}达上限，停止交易")
                time.sleep(5)
                continue

            # ── 止盈止损 ──
            closed = []
            for pos in positions:
                pnl = pos.pnl(up_p, down_p)
                cp  = pos.cur_price(up_p, down_p)
                if pnl >= TP_PCT:
                    log.info(f"🎯 止盈! [{pos.label}] +{pnl*100:.1f}% 入={pos.entry_price:.3f} 现={cp:.3f}")
                    place_order(client, pos.token_id, SELL, cp, pos.size, f"{pos.label}-TP")
                    stats["tp"] += 1; stats["pnl"] += pos.size * pnl
                    closed.append(pos)
                elif pnl <= -SL_PCT:
                    log.info(f"🛑 止损! [{pos.label}] {pnl*100:.1f}% 入={pos.entry_price:.3f} 现={cp:.3f}")
                    place_order(client, pos.token_id, SELL, cp, pos.size, f"{pos.label}-SL")
                    loss = pos.size * abs(pnl)
                    stats["sl"] += 1; stats["pnl"] -= loss; daily_loss += loss
                    closed.append(pos)
            for p in closed:
                positions.remove(p)

            # ══ 策略1：跨周期趋势跟随 ══
            tg_check_commands()
            if not _bot_running:
                log.info("[TG] Bot已停止，跳过交易")
            elif not s1_done and remain > 60:
                direction, strength, desc = trend.analyze()
                log.info(f"S1趋势分析: 方向={direction} 强度={strength} | {desc}")
                if direction == "UP" and S1_MID_LOW <= up_p <= S1_MID_HIGH:
                    log.info(f"📈 [S1] UP趋势(连{strength}期) 价={up_p:.3f} → 买UP ${AMOUNT_S1}")
                    s1_done = True
                    if place_order(client, up_tid, BUY, up_p, AMOUNT_S1, "S1-UP"):
                        positions.append(Position("S1","UP",up_tid,up_p,AMOUNT_S1,"S1-UP"))
                        stats["entries"] += 1
                elif direction == "DOWN" and S1_MID_LOW <= down_p <= S1_MID_HIGH:
                    log.info(f"📉 [S1] DOWN趋势(连{strength}期) 价={down_p:.3f} → 买DOWN ${AMOUNT_S1}")
                    s1_done = True
                    if place_order(client, down_tid, BUY, down_p, AMOUNT_S1, "S1-DOWN"):
                        positions.append(Position("S1","DOWN",down_tid,down_p,AMOUNT_S1,"S1-DOWN"))
                        stats["entries"] += 1
                else:
                    log.info(f"S1: 跳过 (方向={direction} UP={up_p:.3f} DOWN={down_p:.3f})")

            # ══ 策略2：极端价格 ══
            if not s2_done and remain > S2_MIN_SEC:
                if up_p < S2_ENTRY:
                    log.info(f"🔥 [S2] UP极低={up_p:.3f} → 买UP ${AMOUNT_S2}")
                    if place_order(client, up_tid, BUY, up_p, AMOUNT_S2, "S2-UP"):
                        positions.append(Position("S2","UP",up_tid,up_p,AMOUNT_S2,"S2-UP"))
                        stats["entries"] += 1; s2_done = True
                elif down_p < S2_ENTRY:
                    log.info(f"🔥 [S2] DOWN极低={down_p:.3f} → 买DOWN ${AMOUNT_S2}")
                    if place_order(client, down_tid, BUY, down_p, AMOUNT_S2, "S2-DOWN"):
                        positions.append(Position("S2","DOWN",down_tid,down_p,AMOUNT_S2,"S2-DOWN"))
                        stats["entries"] += 1; s2_done = True
                else:
                    log.info(f"S2: UP={up_p:.3f} DOWN={down_p:.3f} 无极端价格(<{S2_ENTRY})")

            # ══ 策略3：结尾追趋势 ══
            if not s3_done and S3_WIN_LOW < remain <= S3_WIN_HIGH:
                if up_p >= S3_THRESHOLD:
                    log.info(f"🚀 [S3] 追UP={up_p:.3f} ≥ {S3_THRESHOLD} → 买UP ${AMOUNT_S3}")
                    if place_order(client, up_tid, BUY, up_p, AMOUNT_S3, "S3-UP"):
                        positions.append(Position("S3","UP",up_tid,up_p,AMOUNT_S3,"S3-UP"))
                        stats["entries"] += 1; s3_done = True
                elif down_p >= S3_THRESHOLD:
                    log.info(f"🚀 [S3] 追DOWN={down_p:.3f} ≥ {S3_THRESHOLD} → 买DOWN ${AMOUNT_S3}")
                    if place_order(client, down_tid, BUY, down_p, AMOUNT_S3, "S3-DOWN"):
                        positions.append(Position("S3","DOWN",down_tid,down_p,AMOUNT_S3,"S3-DOWN"))
                        stats["entries"] += 1; s3_done = True
                else:
                    log.info(f"S3: UP={up_p:.3f} DOWN={down_p:.3f} 未达{S3_THRESHOLD}")

            # 结算
            if remain <= 0:
                for pos in list(positions):
                    pnl = pos.pnl(up_p, down_p)
                    if pnl > 0:
                        log.info(f"✅ 结算盈利 [{pos.label}] +{pnl*100:.1f}%")
                        stats["pnl"] += pos.size * pnl
                    else:
                        log.info(f"❌ 结算亏损 [{pos.label}] {pnl*100:.1f}%")
                        loss = pos.size * abs(pnl); stats["pnl"] -= loss; daily_loss += loss
                    positions.remove(pos)

            time.sleep(5)

    except KeyboardInterrupt:
        log.info("手动停��")
        log.info(f"══ 统计: {stats} ══")

if __name__ == "__main__":
    run()
