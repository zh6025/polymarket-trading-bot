"""
Monitoring: Placeholder module for future monitoring dashboard.

Note: The legacy MonitoringDashboard depended on DataPersistence (now in legacy/).
This stub preserves the module so existing imports don't break, but the implementation
is a no-op. For active bot monitoring, check bot_state.json and container logs.
"""
from datetime import datetime


class MonitoringDashboard:
    """Monitoring dashboard stub (legacy DataPersistence dependency removed)"""

    def get_dashboard_data(self):
        return {
            'timestamp': datetime.now().isoformat(),
            'trades': {'total': 0, 'buy_trades': 0, 'sell_trades': 0, 'recent': []},
            'performance': {},
            'status': 'running',
        }

    def print_dashboard(self):
        data = self.get_dashboard_data()
        print(f"[{data['timestamp']}] MonitoringDashboard: no data (stub)")

