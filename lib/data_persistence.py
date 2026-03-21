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
                outcome TEXT,
                market_slug TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate existing tables: add new columns if they don't exist yet.
        # The column names and types are hardcoded here (not user-supplied),
        # so they are safe to interpolate directly into the ALTER TABLE statement.
        _allowed_migrations = [('outcome', 'TEXT'), ('market_slug', 'TEXT')]
        for col, col_type in _allowed_migrations:
            try:
                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
            except Exception:
                pass  # Column already exists

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
                INSERT INTO trades (order_id, token_id, side, price, size, timestamp, outcome, market_slug)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get('order_id'),
                trade.get('token_id'),
                trade.get('side'),
                trade.get('price'),
                trade.get('size'),
                trade.get('timestamp'),
                trade.get('outcome'),
                trade.get('market_slug'),
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
        """Return a simple performance summary over recent trades.

        Note: the values represent notional amounts (price × size) rather than
        realised PnL, which would require position resolution data.
        """
        try:
            trades = self.get_trades(hours=hours)
            if not trades:
                return {'avg_pnl': 0.0, 'max_pnl': 0.0, 'min_pnl': 0.0, 'total_trades': 0}

            notional_values = [t.get('price', 0.0) * t.get('size', 0.0) for t in trades]
            return {
                'avg_pnl': sum(notional_values) / len(notional_values),
                'max_pnl': max(notional_values),
                'min_pnl': min(notional_values),
                'total_trades': len(trades),
            }
        except Exception as e:
            logger.error(f"Failed to compute performance summary: {e}")
            return {'avg_pnl': 0.0, 'max_pnl': 0.0, 'min_pnl': 0.0, 'total_trades': 0}

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
