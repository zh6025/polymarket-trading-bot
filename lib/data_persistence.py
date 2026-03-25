import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class DataPersistence:
    """Handle data persistence with SQLite"""
    
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.conn = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize database with required tables"""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                order_id TEXT UNIQUE,
                token_id TEXT,
                side TEXT,
                price REAL,
                size REAL,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY,
                token_id TEXT,
                price REAL,
                bid REAL,
                ask REAL,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                total_pnl REAL,
                unrealized_pnl REAL,
                positions JSON,
                statistics JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
        logger.info("Database initialized")
    
    def save_trade(self, trade: Dict[str, Any]) -> bool:
        """Save trade to database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO trades (order_id, token_id, side, price, size, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                trade.get('order_id'),
                trade.get('token_id'),
                trade.get('side'),
                trade.get('price'),
                trade.get('size'),
                trade.get('timestamp')
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
            return False
    
    def save_price(self, token_id: str, price: float, bid: float, ask: float, timestamp: str) -> bool:
        """Save price snapshot"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO prices (token_id, price, bid, ask, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (token_id, price, bid, ask, timestamp))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save price: {e}")
            return False
    
    def get_trades(self, hours: int = 24) -> List[Dict]:
        """Get recent trades"""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(hours=hours)
            cursor.execute("""
                SELECT * FROM trades WHERE created_at > ?
                ORDER BY created_at DESC
            """, (cutoff,))

            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []

    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Return a summary of trading performance over the last N hours."""
        trades = self.get_trades(hours=hours)
        if not trades:
            return {
                "total_trades": 0,
                "buy_trades": 0,
                "sell_trades": 0,
                "avg_price": 0.0,
                "total_volume": 0.0,
                "avg_pnl": 0.0,
                "hours": hours,
            }

        buy_trades = [t for t in trades if t.get("side") == "buy"]
        sell_trades = [t for t in trades if t.get("side") == "sell"]
        prices = [float(t.get("price", 0)) for t in trades if t.get("price")]
        sizes = [float(t.get("size", 0)) for t in trades if t.get("size")]

        avg_price = sum(prices) / len(prices) if prices else 0.0
        total_volume = sum(sizes)

        # Estimate PnL: for each sell trade, compare vs avg buy price
        avg_buy_price = (
            sum(float(t.get("price", 0)) for t in buy_trades) / len(buy_trades)
            if buy_trades else 0.0
        )
        avg_sell_price = (
            sum(float(t.get("price", 0)) for t in sell_trades) / len(sell_trades)
            if sell_trades else 0.0
        )
        avg_pnl = avg_sell_price - avg_buy_price if (buy_trades and sell_trades) else 0.0

        return {
            "total_trades": len(trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "avg_price": round(avg_price, 4),
            "total_volume": round(total_volume, 4),
            "avg_pnl": round(avg_pnl, 4),
            "hours": hours,
        }
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
