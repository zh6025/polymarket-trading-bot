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
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
