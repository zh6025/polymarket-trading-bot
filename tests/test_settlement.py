"""
Tests for the settlement loop in bot_sniper.py and BotState position bookkeeping.
"""
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lib.bot_state import BotState, OpenPosition
from bot_sniper import SniperBot


# ---------------------------------------------------------------------------
# BotState 持仓 / 结算 bookkeeping
# ---------------------------------------------------------------------------
class TestRecordOpenPosition:
    def test_record_creates_open_position(self):
        s = BotState()
        s.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pos = s.record_open_position(
            order_id='o1', token_id='t1', direction='UP',
            entry_price=0.57, size=10.0,
            window_open_ts=1000, window_end_ts=1300,
            market_slug='btc-updown-5m-1000',
        )
        assert pos['order_id'] == 'o1'
        assert s.find_open_position('o1') is pos
        assert len(s.open_positions) == 1

    def test_settle_position_records_pnl_and_moves_to_closed(self):
        s = BotState()
        s.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        s.trading_enabled = True
        s.record_open_position(
            order_id='o1', token_id='t1', direction='UP',
            entry_price=0.57, size=10.0,
            window_open_ts=1000, window_end_ts=1300,
        )
        s.settle_position('o1', pnl=4.30, won=True)
        assert s.find_open_position('o1') is None
        assert len(s.closed_positions) == 1
        assert s.closed_positions[0]['pnl'] == 4.30
        assert s.closed_positions[0]['won'] is True
        # PnL 进入风控
        assert s.daily_pnl == 4.30
        assert s.daily_trade_count == 1

    def test_settle_loss_increments_consecutive_losses(self):
        s = BotState()
        s.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        s.record_open_position('o1', 't1', 'UP', 0.57, 10.0, 1000, 1300)
        s.settle_position('o1', pnl=-5.7, won=False)
        assert s.consecutive_losses == 1
        assert s.daily_pnl == -5.7

    def test_persistence_roundtrip_with_open_position(self, tmp_path):
        s = BotState()
        s.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        s.last_entered_window_ts = 12345
        s.record_open_position('o1', 't1', 'UP', 0.57, 10.0, 1000, 1300, market_slug='slug-x')
        path = str(tmp_path / 'state.json')
        s.save(path)

        loaded = BotState.load(path)
        assert loaded.last_entered_window_ts == 12345
        assert len(loaded.open_positions) == 1
        assert loaded.open_positions[0]['order_id'] == 'o1'
        assert loaded.open_positions[0]['market_slug'] == 'slug-x'


# ---------------------------------------------------------------------------
# SniperBot._settle_finished_windows / _market_won
# ---------------------------------------------------------------------------
class _CfgStub:
    settle_after_end_sec = 60
    state_file = 'unused.json'
    trading_enabled = True
    dry_run = False
    poly_order_type = 'GTC'
    order_fill_timeout_sec = 8
    order_cancel_before_end_sec = 5


def _make_bot(tmp_path, client_mock):
    cfg = _CfgStub()
    cfg.state_file = str(tmp_path / 'state.json')
    state = BotState()
    state.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state.trading_enabled = True
    bot = SniperBot(
        config=cfg,
        client=client_mock,
        state=state,
        feed=MagicMock(),
        strategy=MagicMock(),
        notifier=MagicMock(),
    )
    return bot


class TestSettleFinishedWindows:
    def test_skip_when_window_not_yet_settleable(self, tmp_path):
        client = MagicMock()
        bot = _make_bot(tmp_path, client)
        future_end = int(time.time()) + 600
        bot.state.record_open_position('o1', 't1', 'UP', 0.57, 10.0, 0, future_end)
        asyncio.run(bot._settle_finished_windows())
        assert bot.state.find_open_position('o1') is not None
        client.get_order.assert_not_called()

    def test_settle_winning_position(self, tmp_path):
        client = MagicMock()
        # 订单完全成交
        client.get_order.return_value = {
            'size_matched': '10', 'average_price': '0.57', 'status': 'MATCHED',
        }
        # YES 收盘 1.0 → 赢
        client.get_btc_5m_market_by_slug.return_value = {
            'markets': [
                {'groupItemTitle': 'UP', 'outcomePrices': ['1', '0']},
                {'groupItemTitle': 'DOWN', 'outcomePrices': ['0', '1']},
            ],
        }
        bot = _make_bot(tmp_path, client)
        past_end = int(time.time()) - 120
        bot.state.record_open_position(
            'o1', 't1', 'UP', 0.57, 10.0, 0, past_end, market_slug='btc-updown-5m-x')

        asyncio.run(bot._settle_finished_windows())

        assert bot.state.find_open_position('o1') is None
        closed = bot.state.closed_positions[-1]
        assert closed['won'] is True
        # PnL = (1-0.57)*10 = 4.30
        assert abs(closed['pnl'] - 4.30) < 1e-6
        assert abs(bot.state.daily_pnl - 4.30) < 1e-6

    def test_settle_losing_position(self, tmp_path):
        client = MagicMock()
        client.get_order.return_value = {
            'size_matched': '10', 'average_price': '0.57', 'status': 'MATCHED',
        }
        # UP 收盘 0 → 买 UP 输
        client.get_btc_5m_market_by_slug.return_value = {
            'markets': [
                {'groupItemTitle': 'UP', 'outcomePrices': ['0', '1']},
                {'groupItemTitle': 'DOWN', 'outcomePrices': ['1', '0']},
            ],
        }
        bot = _make_bot(tmp_path, client)
        past_end = int(time.time()) - 120
        bot.state.record_open_position(
            'o1', 't1', 'UP', 0.57, 10.0, 0, past_end, market_slug='btc-updown-5m-x')

        asyncio.run(bot._settle_finished_windows())

        closed = bot.state.closed_positions[-1]
        assert closed['won'] is False
        # PnL = -0.57 * 10 = -5.70
        assert abs(closed['pnl'] - (-5.70)) < 1e-6
        assert bot.state.consecutive_losses == 1

    def test_unfilled_order_settles_zero_pnl(self, tmp_path):
        client = MagicMock()
        client.get_order.return_value = {
            'size_matched': '0', 'average_price': '0.57', 'status': 'CANCELED',
        }
        bot = _make_bot(tmp_path, client)
        past_end = int(time.time()) - 120
        bot.state.record_open_position(
            'o1', 't1', 'UP', 0.57, 10.0, 0, past_end, market_slug='slug-x')

        asyncio.run(bot._settle_finished_windows())

        closed = bot.state.closed_positions[-1]
        assert closed['pnl'] == 0.0
        # 未成交的 trade 仍计 trade_count（policy choice），但不应计连亏
        assert bot.state.consecutive_losses == 0

    def test_circuit_breaker_triggers_after_loss(self, tmp_path):
        """累积亏损超过 daily_loss_limit 时熔断器自动触发。"""
        client = MagicMock()
        client.get_order.return_value = {
            'size_matched': '100', 'average_price': '0.57', 'status': 'MATCHED',
        }
        client.get_btc_5m_market_by_slug.return_value = {
            'markets': [{'groupItemTitle': 'UP', 'outcomePrices': ['0', '1']}],
        }
        bot = _make_bot(tmp_path, client)
        past_end = int(time.time()) - 120
        bot.state.record_open_position(
            'o1', 't1', 'UP', 0.57, 100.0, 0, past_end, market_slug='slug-x')

        asyncio.run(bot._settle_finished_windows())
        # 亏 57 USDC
        assert bot.state.daily_pnl < 0
        # 触发风控判定
        ok, reason = bot.state.can_trade(daily_loss_limit=20)
        assert ok is False
        assert bot.state.circuit_breaker is True
