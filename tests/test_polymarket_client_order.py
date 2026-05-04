"""
Tests for lib/polymarket_client.py — place_order / tick rounding / cancel / balance.

ClobClient 通过 monkeypatch 替换为 mock，避免真实网络。
"""
import os
import pytest
from unittest.mock import MagicMock, patch

from lib.polymarket_client import PolymarketClient, _round_to_tick, _round_size


class TestRounding:
    def test_round_to_tick_001(self):
        assert _round_to_tick(0.5732, 0.01) == 0.57
        assert _round_to_tick(0.5750, 0.01) == 0.58 or _round_to_tick(0.5750, 0.01) == 0.57  # banker's vs std
        assert _round_to_tick(0.6049, 0.01) == 0.60

    def test_round_to_tick_0001(self):
        assert _round_to_tick(0.57321, 0.001) == 0.573

    def test_round_to_tick_passthrough_when_zero(self):
        assert _round_to_tick(0.5, 0) == 0.5

    def test_round_size_floor(self):
        # 截断而非四舍五入，避免超预算
        assert _round_size(8.789, 2) == 8.78
        assert _round_size(8.7891, 2) == 8.78
        assert _round_size(0.005, 2) == 0.0


# ---------------------------------------------------------------------------
# place_order — 用 mock ClobClient 验证参数装配
# ---------------------------------------------------------------------------
class _FakeConfig:
    """构造 PolymarketClient 时不会触发 _init_clob_client（trading_enabled=False）。"""
    poly_private_key = ''
    poly_funder = ''
    poly_chain_id = 137
    poly_signature_type = 2
    poly_clob_host = 'https://clob.polymarket.com'
    poly_api_key = ''
    poly_api_secret = ''
    poly_api_passphrase = ''
    poly_order_type = 'GTC'
    trading_enabled = False
    dry_run = True


@pytest.fixture
def client_with_mock_clob():
    """构造一个 PolymarketClient 并把 _clob 替换为 MagicMock。"""
    pc = PolymarketClient(config=_FakeConfig())
    mock = MagicMock()
    mock.get_tick_size.return_value = '0.01'
    mock.create_and_post_order.return_value = {
        'orderID': 'order-abc123',
        'status': 'LIVE',
    }
    pc._clob = mock
    return pc, mock


class TestPlaceOrder:
    def test_place_buy_order_rounds_price_and_size(self, client_with_mock_clob):
        pc, mock = client_with_mock_clob
        result = pc.place_order(
            token_id='0xtoken',
            side='buy',
            price=0.5734,        # 应被取整到 0.57
            size=10.0,           # 0.57 × 10 = 5.7 USDC，超过最小 5
        )
        assert result['order_id'] == 'order-abc123'
        assert result['price'] == 0.57
        assert result['size'] == 10.0
        assert result['side'] == 'BUY'

        # 校验 OrderArgs 装配
        call_args = mock.create_and_post_order.call_args
        order_args = call_args[0][0]
        assert order_args.token_id == '0xtoken'
        assert order_args.price == 0.57
        assert order_args.size == 10.0
        # side 是字符串常量 BUY/SELL
        assert order_args.side.upper() == 'BUY'

    def test_place_sell_order(self, client_with_mock_clob):
        pc, mock = client_with_mock_clob
        result = pc.place_order(
            token_id='0xtoken', side='SELL', price=0.5731, size=10.0,
        )
        assert result['side'] == 'SELL'
        order_args = mock.create_and_post_order.call_args[0][0]
        assert order_args.side.upper() == 'SELL'

    def test_invalid_side_raises(self, client_with_mock_clob):
        pc, _ = client_with_mock_clob
        with pytest.raises(ValueError):
            pc.place_order(token_id='x', side='hold', price=0.5, size=10)

    def test_below_min_notional_raises(self, client_with_mock_clob):
        pc, _ = client_with_mock_clob
        # 0.5 × 5 = 2.5 USDC < 5
        with pytest.raises(ValueError, match='最小'):
            pc.place_order(token_id='x', side='buy', price=0.5, size=5)

    def test_price_out_of_range_raises(self, client_with_mock_clob):
        pc, _ = client_with_mock_clob
        with pytest.raises(ValueError, match='越界'):
            pc.place_order(token_id='x', side='buy', price=1.05, size=10)

    def test_order_type_fok(self, client_with_mock_clob):
        pc, mock = client_with_mock_clob
        from py_clob_client.clob_types import OrderType
        pc.place_order(token_id='x', side='buy', price=0.57, size=10, order_type='FOK')
        call_args = mock.create_and_post_order.call_args
        # 第二个位置参数是 OrderType 枚举
        assert call_args[0][1] == OrderType.FOK

    def test_invalid_order_type_raises(self, client_with_mock_clob):
        pc, _ = client_with_mock_clob
        with pytest.raises(ValueError):
            pc.place_order(token_id='x', side='buy', price=0.57, size=10, order_type='XYZ')

    def test_get_tick_size_falls_back_on_error(self, client_with_mock_clob):
        pc, mock = client_with_mock_clob
        mock.get_tick_size.side_effect = RuntimeError("boom")
        assert pc.get_tick_size('xx') == 0.01

    def test_cancel_calls_through(self, client_with_mock_clob):
        pc, mock = client_with_mock_clob
        pc.cancel_order('order-1')
        mock.cancel.assert_called_once_with('order-1')


class TestRequireClob:
    def test_require_clob_raises_when_uninitialized(self):
        pc = PolymarketClient(config=_FakeConfig())
        # _clob is None because trading_enabled=False
        with pytest.raises(RuntimeError, match='CLOB'):
            pc.place_order(token_id='x', side='buy', price=0.57, size=10)
