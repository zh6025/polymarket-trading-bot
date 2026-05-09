#!/usr/bin/env python3
"""
Scan recent bot logs and summarize why no live/dry-run entries happened.

Default usage on the server:
    python3 scripts/check_recent_opportunities.py --hours 12

The script reads `docker compose logs --since <hours>h --no-log-prefix bot` by
default. For saved logs/tests, pass `--log-file PATH`.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PRICE_RE = re.compile(r"📊 价格:\s*UP=(?P<up>[0-9.]+)\s+DOWN=(?P<down>[0-9.]+)")
SIGNAL_RE = re.compile(r"🎯 信号:\s*action=(?P<action>[A-Z_]+)\s*\|\s*(?P<reason>.*)")
TIME_SKIP_RE = re.compile(r"剩余(?P<remaining>\d+)s\s+不在\s+\[(?P<low>\d+),\s*(?P<high>\d+)\]s")
PRICE_SKIP_RE = re.compile(r"份额价格(?P<price>[0-9.]+)不在窗口\[(?P<low>[0-9.]+),\s*(?P<high>[0-9.]+)\]")
BET_RE = re.compile(r"💰 下注:")
ORDER_SEND_RE = re.compile(r"📤 下单|✅ 订单响应|✅ 订单已提交")
FILLED_RE = re.compile(r"🎯 订单已完全成交")
FAIL_RE = re.compile(r"订单超时|撤单|下单失败")
BALANCE_RE = re.compile(r"余额|授权")
DRY_RUN_RE = re.compile(r"🔬 DRY-RUN")


@dataclass
class Summary:
    price_samples: int = 0
    signal_samples: int = 0
    skip_time_window: int = 0
    skip_price_window: int = 0
    other_skips: int = 0
    buy_signals: int = 0
    bet_lines: int = 0
    dry_run_lines: int = 0
    order_lines: int = 0
    filled_lines: int = 0
    fail_lines: int = 0
    balance_lines: int = 0
    closest_to_price_window: float | None = None
    price_window_low: float | None = None
    price_window_high: float | None = None
    entry_window_low: int | None = None
    entry_window_high: int | None = None
    last_price: tuple[float, float] | None = None


def _distance_to_window(value: float, low: float, high: float) -> float:
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def analyze_lines(lines: Iterable[str]) -> Summary:
    summary = Summary()

    for line in lines:
        price_match = PRICE_RE.search(line)
        if price_match:
            up = float(price_match.group("up"))
            down = float(price_match.group("down"))
            summary.price_samples += 1
            summary.last_price = (up, down)

        signal_match = SIGNAL_RE.search(line)
        if signal_match:
            summary.signal_samples += 1
            action = signal_match.group("action")
            reason = signal_match.group("reason")
            if action != "SKIP":
                summary.buy_signals += 1
            else:
                time_match = TIME_SKIP_RE.search(reason)
                price_match = PRICE_SKIP_RE.search(reason)
                if time_match:
                    summary.skip_time_window += 1
                    summary.entry_window_low = int(time_match.group("low"))
                    summary.entry_window_high = int(time_match.group("high"))
                elif price_match:
                    summary.skip_price_window += 1
                    price = float(price_match.group("price"))
                    low = float(price_match.group("low"))
                    high = float(price_match.group("high"))
                    summary.price_window_low = low
                    summary.price_window_high = high
                    distance = _distance_to_window(price, low, high)
                    if summary.closest_to_price_window is None or distance < summary.closest_to_price_window:
                        summary.closest_to_price_window = distance
                else:
                    summary.other_skips += 1

        if BET_RE.search(line):
            summary.bet_lines += 1
        if DRY_RUN_RE.search(line):
            summary.dry_run_lines += 1
        if ORDER_SEND_RE.search(line):
            summary.order_lines += 1
        if FILLED_RE.search(line):
            summary.filled_lines += 1
        if FAIL_RE.search(line):
            summary.fail_lines += 1
        if BALANCE_RE.search(line):
            summary.balance_lines += 1

    return summary


def _read_docker_logs(hours: int, service: str) -> list[str]:
    cmd = [
        "docker",
        "compose",
        "logs",
        "--since",
        f"{hours}h",
        "--no-log-prefix",
        service,
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {' '.join(cmd)}")
    return proc.stdout.splitlines()


def _read_lines(args: argparse.Namespace) -> list[str]:
    if args.log_file:
        return Path(args.log_file).read_text(encoding="utf-8").splitlines()
    return _read_docker_logs(args.hours, args.service)


def print_summary(summary: Summary, hours: int) -> None:
    print(f"最近 {hours} 小时机会诊断")
    print("=" * 32)
    print(f"价格样本: {summary.price_samples}")
    print(f"信号样本: {summary.signal_samples}")
    print(f"时间窗口跳过: {summary.skip_time_window}")
    print(f"进入时间窗口但价格不符: {summary.skip_price_window}")
    print(f"其他跳过: {summary.other_skips}")
    print(f"买入信号: {summary.buy_signals}")
    print(f"下注日志: {summary.bet_lines}")
    print(f"DRY-RUN 日志: {summary.dry_run_lines}")
    print(f"下单/订单提交日志: {summary.order_lines}")
    print(f"完全成交日志: {summary.filled_lines}")
    print(f"超时/撤单/失败日志: {summary.fail_lines}")
    print(f"余额/授权日志: {summary.balance_lines}")

    if summary.last_price:
        up, down = summary.last_price
        print(f"最后价格: UP={up:.3f} DOWN={down:.3f}")

    if summary.entry_window_low is not None and summary.entry_window_high is not None:
        print(f"检测到入场时间窗口: [{summary.entry_window_low}, {summary.entry_window_high}]s")
    if summary.price_window_low is not None and summary.price_window_high is not None:
        print(f"检测到价格窗口: [{summary.price_window_low}, {summary.price_window_high}]")
    if summary.closest_to_price_window is not None:
        print(f"距离价格窗口最近差值: {summary.closest_to_price_window:.3f}")

    print()
    if summary.bet_lines == 0 and summary.order_lines == 0:
        print("结论: 这段日志里没有进入下注/下单流程。")
        if summary.skip_price_window:
            print("主要原因: 到达入场秒数时，强势方向价格不在策略价格窗口。")
        elif summary.skip_time_window:
            print("主要原因: 采样时间没有落在策略入场秒数窗口。")
        elif summary.signal_samples == 0:
            print("主要原因: 没有找到策略信号日志，请确认日志来源/服务名。")
    elif summary.order_lines == 0 and summary.dry_run_lines:
        print("结论: 有入场信号，但当前是 DRY_RUN，没有真实下单。")
    elif summary.order_lines:
        print("结论: 已进入下单流程，请结合订单提交/成交/撤单日志继续排查。")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan recent Polymarket bot opportunity logs.")
    parser.add_argument("--hours", type=int, default=12, help="lookback hours for docker compose logs")
    parser.add_argument("--service", default="bot", help="docker compose service name")
    parser.add_argument("--log-file", help="parse an existing log file instead of docker compose logs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        lines = _read_lines(args)
    except Exception as exc:
        print(f"读取日志失败: {exc}", file=sys.stderr)
        print("提示: 请在项目根目录运行，或用 --log-file 指定已保存的日志文件。", file=sys.stderr)
        return 2
    print_summary(analyze_lines(lines), args.hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
