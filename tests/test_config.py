from lib.config import Config


class TestConfigDefaults:
    def test_live_minimum_bet_and_60s_entry_defaults(self, monkeypatch):
        monkeypatch.delenv('BET_SIZE_USDC', raising=False)
        monkeypatch.delenv('SNIPER_ENTRY_SECS', raising=False)

        cfg = Config()

        assert cfg.bet_size_usdc == 5.0
        assert cfg.sniper_entry_secs == 60
