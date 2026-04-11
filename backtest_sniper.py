#!/usr/bin/env python3
"""
backtest_sniper.py — 末端狙击策略回测框架
数据源:
  - Binance Futures 1秒K线 API (fapi.binance.com)
  - 模拟数据模式：GBM几何布朗运动（年化波动率65%）

注意：share价格模拟使用有效波动率(effective_market_vol=2.0)而非纯GBM波动率，
以反映Polymarket真实市场中做市商定价的不确定性溢价（点差、流动性等因素）。
在真实环境中，T=30s时30 bps的BTC移动通常对应约0.60~0.70的份额价格，
而纯GBM模型会高估确定性（给出0.90+的概率）。
"""
import argparse
import json
import math
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from scipy.stats import norm as _norm
    def _normal_cdf(x: float) -> float:
        return float(_norm.cdf(x))
except ImportError:
    def _normal_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

from lib.sniper_strategy import SniperStrategy
from lib.binance_feed import BinanceFeed

# 年化波动率 65%，换算为每秒
_ANNUAL_VOL = 0.65
_VOL_PER_SEC = _ANNUAL_VOL / math.sqrt(365 * 24 * 3600)

# 有效市场波动率（用于share价格模拟）
# 真实Polymarket市场由于点差、流动性溢价、做市商不确定性，
# 有效波动率远高于纯GBM波动率，约为2.0~3.0倍年化
# 推导：在T=30s时，5 bps BTC偏离 → UP份额约0.60 → effective_vol≈2.0
EFFECTIVE_MARKET_VOL = 2.0

# 回测默认参数
DEFAULT_DAYS = 7
WINDOW_SEC = 300          # 5分钟窗口
SNIPE_AT_SEC = 30         # 入场评估时间（距窗口结束剩余秒数）
PRICE_SEED = 50000.0      # GBM模拟起始BTC价格


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    window_idx: int
    window_start_ts: int
    direction: str
    entry_price: float        # 份额价格
    btc_open: float
    btc_at_snipe: float
    btc_final: float
    delta_bps: float
    estimated_prob: float
    edge: float
    kelly_fraction: float
    outcome: str              # 'WIN' | 'LOSS'
    pnl_per_unit: float       # (1 - entry_price) if WIN else -entry_price
    reasoning: str


@dataclass
class BacktestReport:
    total_windows: int = 0
    entered_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    win_rate: float = 0.0
    entry_rate: float = 0.0
    avg_entry_price: float = 0.0
    breakeven_win_rate: float = 0.0
    max_consec_wins: int = 0
    max_consec_losses: int = 0
    hourly_stats: dict = field(default_factory=dict)
    trades: List[TradeRecord] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d['trades'] = [asdict(t) for t in self.trades]
        return d


# ---------------------------------------------------------------------------
# 数据生成
# ---------------------------------------------------------------------------

def generate_gbm_prices(
    n_seconds: int,
    start_price: float = PRICE_SEED,
    annual_vol: float = _ANNUAL_VOL,
    seed: Optional[int] = None,
) -> List[float]:
    """用几何布朗运动(GBM)生成每秒BTC价格序列"""
    rng = random.Random(seed)
    vol_per_sec = annual_vol / math.sqrt(365 * 24 * 3600)
    prices = [start_price]
    price = start_price
    for _ in range(n_seconds - 1):
        z = rng.gauss(0, 1)
        price = price * math.exp(vol_per_sec * z - 0.5 * vol_per_sec ** 2)
        prices.append(price)
    return prices


def fetch_binance_futures_1s(
    symbol: str = "BTCUSDT",
    start_ts_ms: int = None,
    end_ts_ms: int = None,
    limit: int = 1000,
) -> List[Tuple[int, float]]:
    """
    从Binance Futures API获取1秒K线数据。
    返回 [(timestamp_ms, close_price), ...]
    """
    if not HAS_REQUESTS:
        print("requests库未安装，无法使用Binance数据源")
        return []

    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "1s",
        "limit": limit,
    }
    if start_ts_ms:
        params["startTime"] = start_ts_ms
    if end_ts_ms:
        params["endTime"] = end_ts_ms

    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return [(int(k[0]), float(k[4])) for k in data]  # (open_time_ms, close_price)
        else:
            print(f"Binance API 返回 {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"获取Binance数据失败: {e}")
    return []


def download_binance_data(days: int = DEFAULT_DAYS) -> List[Tuple[int, float]]:
    """下载最近N天的Binance 1秒K线数据"""
    print(f"正在下载Binance Futures {days}天1秒K线数据...")
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - days * 86400 * 1000

    all_candles: List[Tuple[int, float]] = []
    batch_start = start_ts

    while batch_start < end_ts:
        batch_end = min(batch_start + 1000 * 1000, end_ts)  # 每批最多1000秒
        candles = fetch_binance_futures_1s(
            start_ts_ms=batch_start,
            end_ts_ms=batch_end,
        )
        if not candles:
            print(f"获取数据为空，停止下载 (batch_start={batch_start})")
            break
        all_candles.extend(candles)
        batch_start = candles[-1][0] + 1000  # 下一批从最后一根K线之后开始
        time.sleep(0.1)  # 避免API限流

        dt = datetime.fromtimestamp(batch_start / 1000, tz=timezone.utc)
        print(f"  已下载至 {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC, 共{len(all_candles)}条")

    print(f"数据下载完成: {len(all_candles)} 条1秒K线")
    return all_candles


# ---------------------------------------------------------------------------
# 回测引擎
# ---------------------------------------------------------------------------

def simulate_share_price(
    btc_return: float,
    remaining_seconds: int,
    annual_vol: float = EFFECTIVE_MARKET_VOL,
) -> float:
    """
    用布朗桥模型估算当前时刻UP份额的市场价格。
    P(UP) = Φ(btc_return / (σ√T_remaining_in_minutes))
    """
    if remaining_seconds <= 0:
        return 1.0 if btc_return > 0 else 0.0
    vol_per_min = annual_vol / math.sqrt(365 * 24 * 60)
    remaining_min = remaining_seconds / 60.0
    vol_remaining = vol_per_min * math.sqrt(remaining_min)
    z = btc_return / vol_remaining if vol_remaining > 1e-9 else 0.0
    return _normal_cdf(z)


def run_backtest(
    prices: List[float],
    strategy: SniperStrategy,
    window_sec: int = WINDOW_SEC,
    snipe_at_sec: int = SNIPE_AT_SEC,
    price_label: str = "模拟",
    annual_vol: float = EFFECTIVE_MARKET_VOL,
) -> BacktestReport:
    """
    对给定的价格序列进行回测。

    参数:
        prices:      每秒BTC价格序列（时间升序）
        strategy:    SniperStrategy实例
        window_sec:  窗口时长（秒）
        snipe_at_sec: 狙击时间点（距窗口结束剩余秒数）
        price_label: 数据来源标签
        annual_vol:  年化波动率（用于布朗桥模拟）
    """
    report = BacktestReport()
    n_windows = len(prices) // window_sec
    report.total_windows = n_windows

    consec_wins = 0
    consec_losses = 0
    cur_consec_wins = 0
    cur_consec_losses = 0

    for w in range(n_windows):
        window_prices = prices[w * window_sec: (w + 1) * window_sec]
        if len(window_prices) < window_sec:
            break

        btc_open = window_prices[0]
        btc_final = window_prices[-1]
        # 狙击时刻：从窗口结束往前数snipe_at_sec秒
        snipe_idx = window_sec - snipe_at_sec
        if snipe_idx < 0 or snipe_idx >= len(window_prices):
            continue
        btc_at_snipe = window_prices[snipe_idx]

        delta_bps = (btc_at_snipe - btc_open) / btc_open * 10_000 if btc_open > 0 else 0.0
        btc_return = (btc_at_snipe - btc_open) / btc_open if btc_open > 0 else 0.0

        # 用布朗桥模型估算份额价格
        up_price = simulate_share_price(btc_return, snipe_at_sec, annual_vol)
        down_price = 1.0 - up_price

        # 用最近snipe_at_sec秒的价格计算动量
        momentum_start_idx = max(0, snipe_idx - strategy.momentum_secs)
        momentum_prices = window_prices[momentum_start_idx:snipe_idx + 1]
        if len(momentum_prices) >= 2:
            mdelta = momentum_prices[-1] - momentum_prices[0]
            mdelta_bps = mdelta / momentum_prices[0] * 10_000 if momentum_prices[0] > 0 else 0.0
            momentum = {
                'direction': 'UP' if mdelta > 0 else ('DOWN' if mdelta < 0 else 'FLAT'),
                'delta': mdelta,
                'delta_bps': mdelta_bps,
                'n_samples': len(momentum_prices),
            }
        else:
            momentum = {'direction': 'FLAT', 'delta': 0.0, 'delta_bps': 0.0, 'n_samples': 0}

        # 狙击评估
        signal = strategy.evaluate(
            remaining_seconds=snipe_at_sec,
            window_open_price=btc_open,
            current_btc_price=btc_at_snipe,
            up_price=up_price,
            down_price=down_price,
            momentum=momentum,
        )

        if signal['action'] == 'SKIP':
            continue

        report.entered_count += 1
        direction = signal['direction']
        entry_price = signal['entry_price']

        # 判断胜负（BTC最终收盘价 vs 开盘价）
        actual_up = btc_final > btc_open
        win = (direction == 'UP' and actual_up) or (direction == 'DOWN' and not actual_up)
        outcome = 'WIN' if win else 'LOSS'
        pnl_per_unit = (1.0 - entry_price) if win else (-entry_price)
        report.total_pnl += pnl_per_unit

        # 统计连胜/连败
        if win:
            report.win_count += 1
            cur_consec_wins += 1
            cur_consec_losses = 0
            consec_wins = max(consec_wins, cur_consec_wins)
        else:
            report.loss_count += 1
            cur_consec_losses += 1
            cur_consec_wins = 0
            consec_losses = max(consec_losses, cur_consec_losses)

        # 按小时统计
        hour_idx = (w * window_sec // 3600) % 24
        if hour_idx not in report.hourly_stats:
            report.hourly_stats[hour_idx] = {'entered': 0, 'wins': 0, 'total_pnl': 0.0}
        report.hourly_stats[hour_idx]['entered'] += 1
        if win:
            report.hourly_stats[hour_idx]['wins'] += 1
        report.hourly_stats[hour_idx]['total_pnl'] += pnl_per_unit

        record = TradeRecord(
            window_idx=w,
            window_start_ts=w * window_sec,
            direction=direction,
            entry_price=entry_price,
            btc_open=btc_open,
            btc_at_snipe=btc_at_snipe,
            btc_final=btc_final,
            delta_bps=delta_bps,
            estimated_prob=signal['estimated_prob'],
            edge=signal['edge'],
            kelly_fraction=signal['kelly_fraction'],
            outcome=outcome,
            pnl_per_unit=pnl_per_unit,
            reasoning=signal['reasoning'],
        )
        report.trades.append(record)

    # 汇总
    report.max_consec_wins = consec_wins
    report.max_consec_losses = consec_losses
    if report.entered_count > 0:
        report.win_rate = report.win_count / report.entered_count
        report.avg_pnl_per_trade = report.total_pnl / report.entered_count
        avg_entry = sum(t.entry_price for t in report.trades) / len(report.trades)
        report.avg_entry_price = round(avg_entry, 4)
        # 盈亏平衡胜率 = entry_price / 1.0（对于单位下注）
        report.breakeven_win_rate = round(avg_entry, 4)
    if report.total_windows > 0:
        report.entry_rate = report.entered_count / report.total_windows

    return report


def print_report(report: BacktestReport, label: str = "回测报告"):
    n = report.entered_count
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  总窗口数:       {report.total_windows}")
    print(f"  入场次数:       {n}  (入场率 {report.entry_rate:.1%})")
    if n == 0:
        print("  未产生任何入场信号")
        return
    print(f"  胜/负:          {report.win_count}/{report.loss_count}")
    print(f"  胜率:           {report.win_rate:.1%}")
    print(f"  盈亏平衡胜率:   {report.breakeven_win_rate:.1%}")
    print(f"  平均入场价:     {report.avg_entry_price:.4f}")
    print(f"  总PnL(每单位):  {report.total_pnl:.4f}")
    print(f"  平均每笔PnL:    {report.avg_pnl_per_trade:.4f}")
    # 每24小时估算（假设每天有288个5分钟窗口）
    windows_per_day = 86400 // 300
    daily_entries = report.entry_rate * windows_per_day
    daily_pnl = daily_entries * report.avg_pnl_per_trade
    print(f"  估算每日入场:   {daily_entries:.1f} 次")
    print(f"  估算每日PnL:    {daily_pnl:.4f} 单位/天")
    print(f"  最长连赢:       {report.max_consec_wins}")
    print(f"  最长连败:       {report.max_consec_losses}")

    print(f"\n  按小时入场统计:")
    for h in sorted(report.hourly_stats.keys()):
        s = report.hourly_stats[h]
        cnt = s['entered']
        wr = s['wins'] / cnt if cnt > 0 else 0.0
        print(f"    {h:02d}:00  入场={cnt}  胜率={wr:.1%}  PnL={s['total_pnl']:.4f}")
    print(f"{'='*60}\n")


def sensitivity_analysis(
    prices: List[float],
    window_sec: int = WINDOW_SEC,
    snipe_at_sec: int = SNIPE_AT_SEC,
):
    """灵敏度分析：不同参数组合对比"""
    print("\n灵敏度分析（参数扫描）")
    print(f"{'参数组合':<40} {'入场率':>8} {'胜率':>8} {'均PnL':>8} {'总PnL':>8}")
    print("-" * 72)

    for price_min, price_max in [(0.52, 0.58), (0.55, 0.60), (0.55, 0.65), (0.50, 0.60)]:
        for min_delta_bps in [1.0, 2.0, 5.0]:
            strat = SniperStrategy(
                entry_secs=snipe_at_sec,
                entry_window_low=snipe_at_sec - 5,
                entry_window_high=snipe_at_sec + 5,
                price_min=price_min,
                price_max=price_max,
                min_delta_bps=min_delta_bps,
            )
            r = run_backtest(prices, strat, window_sec, snipe_at_sec)
            if r.entered_count == 0:
                continue
            label = f"价格[{price_min:.2f},{price_max:.2f}] δ>={min_delta_bps:.0f}bps"
            print(f"  {label:<38} {r.entry_rate:>7.1%} {r.win_rate:>7.1%} "
                  f"{r.avg_pnl_per_trade:>7.4f} {r.total_pnl:>7.4f}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="末端狙击策略回测")
    parser.add_argument("--mode", choices=["simulate", "binance"], default="simulate",
                        help="数据模式: simulate=GBM模拟 binance=Binance实时数据")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help="回测天数（默认7天）")
    parser.add_argument("--seed", type=int, default=42,
                        help="GBM随机种子（simulate模式）")
    parser.add_argument("--price-min", type=float, default=0.55, dest="price_min",
                        help="份额价格下限")
    parser.add_argument("--price-max", type=float, default=0.60, dest="price_max",
                        help="份额价格上限")
    parser.add_argument("--min-delta-bps", type=float, default=2.0, dest="min_delta_bps",
                        help="BTC最小偏离基点")
    parser.add_argument("--snipe-at", type=int, default=SNIPE_AT_SEC, dest="snipe_at",
                        help="狙击时间点（距窗口结束剩余秒数）")
    parser.add_argument("--sensitivity", action="store_true",
                        help="运行灵敏度分析")
    parser.add_argument("--output", type=str, default=None,
                        help="交易明细输出JSON文件路径")
    args = parser.parse_args()

    # 数据准备
    if args.mode == "binance":
        print("使用Binance Futures 1秒K线数据")
        candles = download_binance_data(days=args.days)
        if not candles:
            print("下载数据失败，回退到GBM模拟模式")
            prices = generate_gbm_prices(
                n_seconds=args.days * 86400,
                start_price=PRICE_SEED,
                seed=args.seed,
            )
            label = f"GBM模拟 ({args.days}天)"
        else:
            prices = [p for _, p in candles]
            label = f"Binance实际数据 ({args.days}天)"
    else:
        print(f"使用GBM模拟数据（{args.days}天，seed={args.seed}）")
        prices = generate_gbm_prices(
            n_seconds=args.days * 86400,
            start_price=PRICE_SEED,
            seed=args.seed,
        )
        label = f"GBM模拟 ({args.days}天)"

    # 构建策略
    strategy = SniperStrategy(
        entry_secs=args.snipe_at,
        entry_window_low=args.snipe_at - 5,
        entry_window_high=args.snipe_at + 5,
        price_min=args.price_min,
        price_max=args.price_max,
        min_delta_bps=args.min_delta_bps,
    )

    # 运行回测
    report = run_backtest(
        prices=prices,
        strategy=strategy,
        window_sec=WINDOW_SEC,
        snipe_at_sec=args.snipe_at,
    )

    print_report(report, label=label)

    # 灵敏度分析
    if args.sensitivity:
        sensitivity_analysis(prices, snipe_at_sec=args.snipe_at)

    # 导出交易明细
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"交易明细已保存: {args.output}")


if __name__ == "__main__":
    main()
