import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_recent_opportunities.py"
    spec = importlib.util.spec_from_file_location("check_recent_opportunities", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_analyze_lines_counts_time_and_price_skips():
    module = _load_module()
    lines = [
        "[INFO] 📊 价格: UP=0.995 DOWN=0.005",
        "[INFO] 🎯 信号: action=SKIP | 时间窗口不符: 剩余40s 不在 [25, 35]s",
        "[INFO] 📊 价格: UP=0.995 DOWN=0.005",
        "[INFO] 🎯 信号: action=SKIP | 份额价格0.995不在窗口[0.55, 0.6]",
        "[INFO] 💵 USDC 余额=10.0000 授权额度=10.0000 需要=1.0000",
    ]

    summary = module.analyze_lines(lines)

    assert summary.price_samples == 2
    assert summary.signal_samples == 2
    assert summary.skip_time_window == 1
    assert summary.skip_price_window == 1
    assert summary.balance_lines == 1
    assert summary.entry_window_low == 25
    assert summary.entry_window_high == 35
    assert summary.price_window_low == 0.55
    assert summary.price_window_high == 0.6
    assert summary.closest_to_price_window == 0.395


def test_analyze_lines_counts_order_flow():
    module = _load_module()
    lines = [
        "[INFO] 🎯 信号: action=BUY_UP | ok",
        "[INFO] 💰 下注: UP @ 0.560 size=1.00 USDC",
        "[INFO] 🔬 DRY-RUN: UP @ 0.560 x 1.7857 份额",
        "[INFO] ✅ 订单已提交: UP @ 0.560 x 1.7857 份额 (order_id=abc)",
        "[INFO] 🎯 订单已完全成交: abc status=MATCHED",
        "[WARN] ⏱ 订单超时/接近窗口结束，已发起撤单: def",
    ]

    summary = module.analyze_lines(lines)

    assert summary.buy_signals == 1
    assert summary.bet_lines == 1
    assert summary.dry_run_lines == 1
    assert summary.order_lines == 1
    assert summary.filled_lines == 1
    assert summary.fail_lines == 1


def test_rejects_invalid_compose_service_name():
    module = _load_module()

    with pytest.raises(ValueError):
        module._read_docker_logs(12, "bot;rm -rf /")
