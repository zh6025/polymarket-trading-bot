"""
Telegram 告警工具：在熔断 / 下单失败 / 余额不足等关键事件时推送消息。
仅在配置了 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 时启用，否则静默 no-op。
"""
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = (bot_token or '').strip()
        self.chat_id = (chat_id or '').strip()

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def notify(self, message: str, level: str = 'info') -> bool:
        """推送消息到 Telegram；失败时打印日志，不抛异常。返回是否成功。"""
        prefix = {'info': 'ℹ️', 'warn': '⚠️', 'error': '🚨'}.get(level, 'ℹ️')
        full_msg = f"{prefix} [Polymarket Bot] {message}"
        if not self.enabled:
            log.debug(f"Notifier disabled, skip: {full_msg}")
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = requests.post(
                url,
                json={'chat_id': self.chat_id, 'text': full_msg},
                timeout=5,
            )
            if resp.status_code == 200:
                return True
            log.warning(f"Telegram notify 返回 {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.warning(f"Telegram notify 失败: {e}")
        return False
