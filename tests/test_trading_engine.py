from lib.trading_engine import TradingEngine


def test_place_order_fills_immediately_in_dry_run():
    engine = TradingEngine(dry_run=True)

    order_id = engine.place_order('token-1', 'buy', 0.55, 3)

    assert engine.orders[order_id]['status'] == 'filled'
    assert engine.positions['token-1'] == 3
    assert len(engine.trades) == 1


def test_place_order_stays_pending_in_live_mode():
    engine = TradingEngine(dry_run=False)

    order_id = engine.place_order('token-1', 'sell', 0.6, 2)

    assert engine.orders[order_id]['status'] == 'pending'
    assert engine.positions == {}
    assert engine.trades == []
