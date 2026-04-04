import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.dry_run = self.get_bool('DRY_RUN', default=True)
        self.order_size = self.get_float('ORDER_SIZE', default=5.0)
        self.check_interval_sec = max(1, int(self.get_float('CHECK_INTERVAL_SEC', default=5.0)))

    @staticmethod
    def get_env_variable(var_name, default=None):
        value = os.getenv(var_name)
        return default if value is None else value

    def get_bool(self, var_name, default=False):
        value = self.get_env_variable(var_name)
        if value is None:
            return default
        return str(value).strip().lower() == 'true'

    def get_float(self, var_name, default=0.0):
        value = self.get_env_variable(var_name)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
