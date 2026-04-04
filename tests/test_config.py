from lib.config import Config


def test_config_uses_defaults(monkeypatch):
    monkeypatch.delenv('DRY_RUN', raising=False)
    monkeypatch.delenv('ORDER_SIZE', raising=False)
    monkeypatch.delenv('CHECK_INTERVAL_SEC', raising=False)

    config = Config()

    assert config.dry_run is True
    assert config.order_size == 5.0
    assert config.check_interval_sec == 5


def test_config_parses_env_values(monkeypatch):
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setenv('ORDER_SIZE', '2.5')
    monkeypatch.setenv('CHECK_INTERVAL_SEC', '0')

    config = Config()

    assert config.dry_run is False
    assert config.order_size == 2.5
    assert config.check_interval_sec == 1


def test_config_clamps_negative_interval_and_ignores_invalid_float(monkeypatch):
    monkeypatch.setenv('ORDER_SIZE', 'invalid')
    monkeypatch.setenv('CHECK_INTERVAL_SEC', '-3')

    config = Config()

    assert config.order_size == 5.0
    assert config.check_interval_sec == 1
