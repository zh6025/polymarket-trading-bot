#!/usr/bin/env python3
"""
检查最近 N 小时机器人日志里是否出现过“可入场/可成交”的窗口。

默认读取 docker compose 最近 8 小时日志：
    python3 scripts/check_recent_opportunities.py

也可以分析已导出的日志：
    docker compose logs --since=8h bot > /tmp/bot.log
    python3 scripts/check_recent_opportunities.py --log-file /tmp/bot.log

说明：
    这个脚本基于 bot 自己打印的入场窗口日志判断机会：
    - 进入入场窗口并打印 “📊 价格: UP=... DOWN=...”
    - 最高份额价格落在 SNIPER_PRICE_MIN/SNIPER_PRICE_MAX
    - 或策略信号打印 action=BUY_UP / BUY_DOWN
    如果 8 小时没有任何入场窗口评估，通常说明 bot 没跑、日志没读到，或轮询错过入场窗口。
"""
import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional


DEFAULT_HOURS = 8
DEFAULT_PRICE_MIN = float(os.environ.get("SNIPER_PRICE_MIN", "0.55"))
DEFAULT_PRICE_MAX = float(os.environ.get("SNIPER_PRICE_MAX", "0.60"))

MARKET_RE = re.compile(r"slug=(btc-[^|\s]+).*remaining=(-?\d+)s")
WINDOW_RE = re.compile(r"窗口: open_ts=(\d+) remaining=(-?\d+)s")
PRICE_RE = re.compile(r"价格: UP=([0-9.]+) DOWN=([0-9.]+)")
SIGNAL_RE = re.compile(r"信号: action=(BUY_UP|BUY_DOWN|SKIP)\s*\|\s*(.*)")
DRY_RUN_RE = re.compile(r"DRY-RUN:\s*(UP|DOWN)\s*@\s*([0-9.]+)")
LIVE_ORDER_RE = re.compile(r"订单已提交:\s*(UP|DOWN)\s*@\s*([0-9.]+)")


@dataclass
class WindowOpportunity:
    window_open_ts: Optional[int] = None
    slug: str = ""
    last_remaining: Optional[int] = None
    up_price: Optional[float] = None
    down_price: Optional[float] = None
    signal_action: str = ""
    signal_reason: str = ""
    dry_run_entry: bool = False
    live_order: bool = False

    @property
    def key(self) -> str:
        if self.window_open_ts is not None:
            return str(self.window_open_ts)
        return self.slug or "unknown"

    @property
    def best_direction(self) -> str:
        if self.up_price is None or self.down_price is None:
            return ""
        if self.up_price > self.down_price:
            return "UP"
        if self.down_price > self.up_price:
            return "DOWN"
        return "FLAT"

    @property
    def best_price(self) -> Optional[float]:
        prices = [p for p in (self.up_price, self.down_price) if p is not None]
        return max(prices) if prices else None

    def has_price_opportunity(self, price_min: float, price_max: float) -> bool:
        best = self.best_price
        return best is not None and price_min <= best <= price_max

    def has_buy_signal(self) -> bool:
        return self.signal_action in {"BUY_UP", "BUY_DOWN"}

    def has_entry_record(self) -> bool:
        return self.dry_run_entry or self.live_order

    def utc_window(self) -> str:
        if self.window_open_ts is None:
            return "N/A"
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(self.window_open_ts))


def _parse_slug_ts(slug: str) -> Optional[int]:
    try:
        return int(slug.rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def _current_record(records: dict[str, WindowOpportunity], current_key: Optional[str]) -> WindowOpportunity:
    if current_key and current_key in records:
        return records[current_key]
    rec = WindowOpportunity()
    records[rec.key] = rec
    return rec


def parse_log_lines(lines: Iterable[str], price_min: float, price_max: float) -> list[WindowOpportunity]:
    records: dict[str, WindowOpportunity] = {}
    current_key: Optional[str] = None

    for line in lines:
        market_match = MARKET_RE.search(line)
        if market_match:
            slug = market_match.group(1)
            ts = _parse_slug_ts(slug)
            key = str(ts) if ts is not None else slug
            rec = records.setdefault(key, WindowOpportunity(window_open_ts=ts, slug=slug))
            rec.slug = slug
            rec.window_open_ts = ts
            rec.last_remaining = int(market_match.group(2))
            current_key = key

        window_match = WINDOW_RE.search(line)
        if window_match:
            ts = int(window_match.group(1))
            key = str(ts)
            rec = records.setdefault(key, WindowOpportunity(window_open_ts=ts))
            rec.window_open_ts = ts
            rec.last_remaining = int(window_match.group(2))
            current_key = key

        price_match = PRICE_RE.search(line)
        if price_match:
            rec = _current_record(records, current_key)
            rec.up_price = float(price_match.group(1))
            rec.down_price = float(price_match.group(2))

        signal_match = SIGNAL_RE.search(line)
        if signal_match:
            rec = _current_record(records, current_key)
            rec.signal_action = signal_match.group(1)
            rec.signal_reason = signal_match.group(2).strip()

        dry_match = DRY_RUN_RE.search(line)
        if dry_match:
            rec = _current_record(records, current_key)
            rec.dry_run_entry = True
            if rec.signal_action == "":
                rec.signal_action = f"BUY_{dry_match.group(1)}"

        live_match = LIVE_ORDER_RE.search(line)
        if live_match:
            rec = _current_record(records, current_key)
            rec.live_order = True
            if rec.signal_action == "":
                rec.signal_action = f"BUY_{live_match.group(1)}"

    useful = [
        rec for rec in records.values()
        if rec.window_open_ts is not None
        and (
            rec.up_price is not None
            or rec.down_price is not None
            or rec.signal_action
            or rec.has_entry_record()
        )
    ]
    useful.sort(key=lambda r: r.window_open_ts or 0)

    # price_min/price_max 由调用方传入；这里引用一次避免未来误删参数导致测试漏掉。
    _ = (price_min, price_max)
    return useful


def read_logs(hours: int, log_file: Optional[str], tail: int) -> list[str]:
    if log_file:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            return f.readlines()

    cmd = ["docker", "compose", "logs", f"--since={hours}h", f"--tail={tail}", "bot"]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        print("❌ 无法读取 docker compose 日志：", file=sys.stderr)
        print(proc.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return proc.stdout.splitlines()


def print_report(records: list[WindowOpportunity], price_min: float, price_max: float, hours: int) -> int:
    evaluated = [r for r in records if r.up_price is not None and r.down_price is not None]
    opportunities = [r for r in records if r.has_buy_signal() or r.has_price_opportunity(price_min, price_max)]
    entries = [r for r in records if r.has_entry_record()]

    print(f"===== 最近 {hours} 小时可成交窗口检查 =====")
    print(f"策略价格窗口: [{price_min:.3f}, {price_max:.3f}]")
    print(f"入场窗口评估数: {len(evaluated)}")
    print(f"可成交/可入场机会数: {len(opportunities)}")
    print(f"已记录 DRY_RUN/实盘入场数: {len(entries)}")
    print()

    if opportunities:
        print("可成交/可入场窗口：")
        print("UTC窗口              方向  价格     信号      执行记录  slug")
        for rec in opportunities:
            best = rec.best_price
            best_str = f"{best:.3f}" if best is not None else "N/A"
            executed = "LIVE" if rec.live_order else ("DRY_RUN" if rec.dry_run_entry else "-")
            print(
                f"{rec.utc_window():<20} "
                f"{rec.best_direction or '-':<4} "
                f"{best_str:<7} "
                f"{rec.signal_action or '-':<9} "
                f"{executed:<8} "
                f"{rec.slug or '-'}"
            )
    else:
        print("❌ 最近日志中没有找到任何可成交/可入场窗口。")

    if not evaluated:
        print("\n❌ 也没有找到任何入场窗口评估（没有“📊 价格”日志）。")
        print("请先确认 bot 是否持续运行、docker 日志是否可读、轮询是否错过 25-35 秒入场窗口。")
        return 2

    if not opportunities:
        print("\n❌ 8 小时没有任何机会，按当前策略/日志看机器人很可能有问题，需要排查价格源、市场识别或入场窗口。")
        return 3

    print("\n✅ 最近日志中存在可成交/可入场窗口；如果没有实际成交，请继续排查下单、余额/授权、订单类型或成交监控。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查最近 N 小时 bot 日志中的可成交窗口")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="读取最近多少小时 docker 日志，默认 8")
    parser.add_argument("--log-file", help="改为读取指定日志文件")
    parser.add_argument("--tail", type=int, default=20000, help="docker logs 最大行数，默认 20000")
    parser.add_argument("--price-min", type=float, default=DEFAULT_PRICE_MIN, help="份额价格下限")
    parser.add_argument("--price-max", type=float, default=DEFAULT_PRICE_MAX, help="份额价格上限")
    args = parser.parse_args()

    lines = read_logs(args.hours, args.log_file, args.tail)
    records = parse_log_lines(lines, args.price_min, args.price_max)
    return print_report(records, args.price_min, args.price_max, args.hours)


if __name__ == "__main__":
    sys.exit(main())
