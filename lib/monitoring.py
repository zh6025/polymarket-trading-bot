from datetime import datetime
from lib.data_persistence import DataPersistence

class MonitoringDashboard:
    """Real-time monitoring dashboard"""
    
    def __init__(self):
        self.db = DataPersistence()
    
    def get_dashboard_data(self):
        """Get all dashboard metrics"""
        trades = self.db.get_trades(hours=24)
        performance = self.db.get_performance_summary(hours=24)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'trades': {
                'total': len(trades),
                'buy_trades': len([t for t in trades if t.get('side') == 'buy']),
                'sell_trades': len([t for t in trades if t.get('side') == 'sell']),
                'recent': trades[:10]
            },
            'performance': performance,
            'status': 'running'
        }
    
    def print_dashboard(self):
        """Print formatted dashboard"""
        data = self.get_dashboard_data()
        
        print("\n" + "="*70)
        print("POLYMARKET TRADING BOT - MONITORING DASHBOARD")
        print("="*70)
        print(f"Timestamp: {data['timestamp']}")
        print("-"*70)
        print(f"Total Trades (24h):     {data['trades']['total']}")
        print(f"Buy Orders:             {data['trades']['buy_trades']}")
        print(f"Sell Orders:            {data['trades']['sell_trades']}")
        print(f"Avg PnL:                ${data['performance'].get('avg_pnl', 0):.2f}")
        print("="*70 + "\n")
