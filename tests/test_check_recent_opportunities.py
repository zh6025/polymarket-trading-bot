import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_recent_opportunities.py"
spec = importlib.util.spec_from_file_location("check_recent_opportunities", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parse_buy_signal_and_dry_run_entry():
    lines = [
        "bot | 🧾 市场详情: title=x | slug=btc-updown-5m-1710000000 | window=x | remaining=31s | active_markets=1/1",
        "bot | 📅 窗口: open_ts=1710000000 remaining=31s",
        "bot | 📊 价格: UP=0.570 DOWN=0.430",
        "bot | 🎯 信号: action=BUY_UP | ✅ 末端狙击: UP @ 0.570",
        "bot | 🔬 DRY-RUN: UP @ 0.570 x 1.7543 份额 (~1.00 USDC，跳过真实下单）",
    ]

    records = mod.parse_log_lines(lines, 0.55, 0.60)

    assert len(records) == 1
    rec = records[0]
    assert rec.window_open_ts == 1710000000
    assert rec.best_direction == "UP"
    assert rec.has_buy_signal()
    assert rec.has_price_opportunity(0.55, 0.60)
    assert rec.has_entry_record()


def test_parse_price_opportunity_even_without_signal():
    lines = [
        "bot | 📅 窗口: open_ts=1710000300 remaining=30s",
        "bot | 📊 价格: UP=0.410 DOWN=0.590",
    ]

    records = mod.parse_log_lines(lines, 0.55, 0.60)

    assert len(records) == 1
    rec = records[0]
    assert rec.best_direction == "DOWN"
    assert rec.best_price == 0.590
    assert rec.has_price_opportunity(0.55, 0.60)
    assert not rec.has_entry_record()


def test_parse_no_opportunity_when_price_outside_window():
    lines = [
        "bot | 📅 窗口: open_ts=1710000600 remaining=30s",
        "bot | 📊 价格: UP=0.700 DOWN=0.300",
        "bot | 🎯 信号: action=SKIP | 份额价格0.700不在窗口[0.55, 0.6]",
    ]

    records = mod.parse_log_lines(lines, 0.55, 0.60)

    assert len(records) == 1
    rec = records[0]
    assert not rec.has_buy_signal()
    assert not rec.has_price_opportunity(0.55, 0.60)


def test_print_report_with_opportunity(capsys):
    records = mod.parse_log_lines([
        "bot | 📅 窗口: open_ts=1710000000 remaining=31s",
        "bot | 📊 价格: UP=0.570 DOWN=0.430",
        "bot | 🎯 信号: action=BUY_UP | ✅ 末端狙击: UP @ 0.570",
    ], 0.55, 0.60)

    exit_code = mod.print_report(records, 0.55, 0.60, 8)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "可成交/可入场机会数: 1" in output
    assert "BUY_UP" in output
