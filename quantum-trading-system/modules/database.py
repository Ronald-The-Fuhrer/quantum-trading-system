"""
Database Manager - SQLite with optimization and thread safety
"""

import sqlite3
import threading
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import logging

logger = logging.getLogger(__name__)


class QuantumDatabase:
    """Thread-safe database manager with optimization"""
    
    def __init__(self, db_path: str = 'quantum_trading.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.conn = None
        self._connect()
        self._init_tables()
        self._optimize_db()
        logger.info(f"✓ Database initialized: {db_path}")
    
    def _connect(self):
        """Create database connection"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
    
    def _init_tables(self):
        """Initialize all database tables"""
        with self.lock:
            cursor = self.conn.cursor()
            
            # Trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    asset_type TEXT,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    strategy TEXT,
                    confidence REAL,
                    pnl REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    slippage REAL DEFAULT 0,
                    order_id TEXT,
                    notes TEXT,
                    UNIQUE(order_id)
                )
            ''')
            
            # Portfolio history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_value REAL NOT NULL,
                    cash REAL NOT NULL,
                    positions_value REAL NOT NULL,
                    daily_pnl REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    sharpe_ratio REAL,
                    drawdown REAL,
                    num_positions INTEGER DEFAULT 0
                )
            ''')
            
            # Positions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    asset_type TEXT,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    strategy TEXT,
                    unrealized_pnl REAL DEFAULT 0,
                    position_type TEXT,
                    UNIQUE(ticker, timestamp)
                )
            ''')
            
            # Strategy performance
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    trades_count INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    avg_profit REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0
                )
            ''')
            
            # Market data cache
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_data_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data BLOB,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, timeframe, timestamp)
                )
            ''')
            
            # Model performance
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS model_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    accuracy REAL,
                    precision_score REAL,
                    recall_score REAL,
                    f1_score REAL,
                    sharpe_ratio REAL
                )
            ''')
            
            # Backtest results
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    total_return REAL,
                    sharpe_ratio REAL,
                    sortino_ratio REAL,
                    max_drawdown REAL,
                    win_rate REAL,
                    profit_factor REAL,
                    total_trades INTEGER,
                    avg_trade REAL,
                    best_trade REAL,
                    worst_trade REAL,
                    config TEXT
                )
            ''')
            
            # Orders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price REAL,
                    stop_price REAL,
                    status TEXT DEFAULT 'pending',
                    filled_price REAL,
                    filled_quantity REAL,
                    filled_at TEXT,
                    strategy TEXT,
                    notes TEXT
                )
            ''')
            
            # Risk events
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT,
                    portfolio_value REAL,
                    drawdown REAL,
                    action_taken TEXT
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_timestamp ON portfolio_history(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_market_data_ticker ON market_data_cache(ticker)')
            
            self.conn.commit()
            logger.info("✓ Database tables initialized")
    
    def _optimize_db(self):
        """Optimize database for performance"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA cache_size=10000')
            cursor.execute('PRAGMA temp_store=MEMORY')
            cursor.execute('PRAGMA mmap_size=30000000000')
            self.conn.commit()
    
    def log_trade(self, trade_data: Dict):
        """Log a trade"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO trades (timestamp, ticker, asset_type, action, quantity, 
                                  price, strategy, confidence, pnl, commission, slippage, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_data.get('timestamp', datetime.now().isoformat()),
                trade_data['ticker'],
                trade_data.get('asset_type', 'stock'),
                trade_data['action'],
                trade_data['quantity'],
                trade_data['price'],
                trade_data.get('strategy', ''),
                trade_data.get('confidence', 0.0),
                trade_data.get('pnl', 0.0),
                trade_data.get('commission', 0.0),
                trade_data.get('slippage', 0.0),
                trade_data.get('order_id', '')
            ))
            self.conn.commit()
    
    def log_portfolio_snapshot(self, timestamp: datetime, total_value: float,
                              cash: float, positions_value: float, daily_pnl: float = 0,
                              total_pnl: float = 0, sharpe_ratio: float = 0,
                              drawdown: float = 0, num_positions: int = 0):
        """Log portfolio snapshot"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO portfolio_history 
                (timestamp, total_value, cash, positions_value, daily_pnl, 
                 total_pnl, sharpe_ratio, drawdown, num_positions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp.isoformat(), total_value, cash, positions_value,
                  daily_pnl, total_pnl, sharpe_ratio, drawdown, num_positions))
            self.conn.commit()
    
    def log_position(self, position_data: Dict):
        """Log a position"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (timestamp, ticker, asset_type, quantity, entry_price, current_price,
                 stop_loss, take_profit, strategy, unrealized_pnl, position_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                position_data['ticker'],
                position_data.get('asset_type', 'stock'),
                position_data['quantity'],
                position_data['entry_price'],
                position_data.get('current_price', 0),
                position_data.get('stop_loss', 0),
                position_data.get('take_profit', 0),
                position_data.get('strategy', ''),
                position_data.get('unrealized_pnl', 0),
                position_data.get('position_type', 'long')
            ))
            self.conn.commit()
    
    def log_order(self, order_data: Dict):
        """Log an order"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO orders 
                (order_id, timestamp, ticker, action, quantity, order_type,
                 limit_price, stop_price, status, strategy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_data['order_id'],
                datetime.now().isoformat(),
                order_data['ticker'],
                order_data['action'],
                order_data['quantity'],
                order_data.get('order_type', 'market'),
                order_data.get('limit_price'),
                order_data.get('stop_price'),
                order_data.get('status', 'pending'),
                order_data.get('strategy', '')
            ))
            self.conn.commit()
    
    def update_order_status(self, order_id: str, status: str, 
                          filled_price: float = None, filled_quantity: float = None):
        """Update order status"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE orders SET status = ?, filled_price = ?, 
                filled_quantity = ?, filled_at = ?
                WHERE order_id = ?
            ''', (status, filled_price, filled_quantity, 
                  datetime.now().isoformat() if status == 'filled' else None,
                  order_id))
            self.conn.commit()
    
    def log_backtest_result(self, result_data: Dict):
        """Log backtest result"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO backtest_results 
                (timestamp, strategy_name, start_date, end_date, total_return,
                 sharpe_ratio, sortino_ratio, max_drawdown, win_rate, profit_factor,
                 total_trades, avg_trade, best_trade, worst_trade, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                result_data['strategy_name'],
                result_data['start_date'],
                result_data['end_date'],
                result_data.get('total_return', 0),
                result_data.get('sharpe_ratio', 0),
                result_data.get('sortino_ratio', 0),
                result_data.get('max_drawdown', 0),
                result_data.get('win_rate', 0),
                result_data.get('profit_factor', 0),
                result_data.get('total_trades', 0),
                result_data.get('avg_trade', 0),
                result_data.get('best_trade', 0),
                result_data.get('worst_trade', 0),
                json.dumps(result_data.get('config', {}))
            ))
            self.conn.commit()
    
    def log_risk_event(self, event_type: str, severity: str, description: str,
                      portfolio_value: float = 0, drawdown: float = 0, action_taken: str = ''):
        """Log risk event"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO risk_events 
                (timestamp, event_type, severity, description, portfolio_value, drawdown, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (datetime.now().isoformat(), event_type, severity, description,
                  portfolio_value, drawdown, action_taken))
            self.conn.commit()
    
    def get_trades_history(self, days: int = 30, ticker: str = None, 
                          strategy: str = None) -> pd.DataFrame:
        """Get trade history"""
        query = '''
            SELECT * FROM trades 
            WHERE timestamp >= datetime('now', '-{} days')
        '''.format(days)
        
        if ticker:
            query += f" AND ticker = '{ticker}'"
        if strategy:
            query += f" AND strategy = '{strategy}'"
        
        query += ' ORDER BY timestamp DESC'
        
        return pd.read_sql_query(query, self.conn)
    
    def get_portfolio_history(self, days: int = 30) -> pd.DataFrame:
        """Get portfolio history"""
        query = f'''
            SELECT * FROM portfolio_history 
            WHERE timestamp >= datetime('now', '-{days} days')
            ORDER BY timestamp ASC
        '''
        return pd.read_sql_query(query, self.conn)
    
    def get_current_positions(self) -> pd.DataFrame:
        """Get current positions"""
        query = '''
            SELECT * FROM positions 
            WHERE timestamp = (SELECT MAX(timestamp) FROM positions)
        '''
        return pd.read_sql_query(query, self.conn)
    
    def get_strategy_performance(self, strategy: str = None) -> pd.DataFrame:
        """Get strategy performance metrics"""
        query = 'SELECT * FROM strategy_performance'
        if strategy:
            query += f" WHERE strategy_name = '{strategy}'"
        query += ' ORDER BY timestamp DESC LIMIT 100'
        return pd.read_sql_query(query, self.conn)
    
    def get_backtest_results(self, strategy: str = None) -> pd.DataFrame:
        """Get backtest results"""
        query = 'SELECT * FROM backtest_results'
        if strategy:
            query += f" WHERE strategy_name = '{strategy}'"
        query += ' ORDER BY timestamp DESC'
        return pd.read_sql_query(query, self.conn)
    
    def cleanup_old_data(self, days: int = 365):
        """Clean up old data"""
        with self.lock:
            cursor = self.conn.cursor()
            cutoff = f"datetime('now', '-{days} days')"
            
            # Keep trades and portfolio history
            # Delete old market data cache
            cursor.execute(f'''
                DELETE FROM market_data_cache 
                WHERE created_at < {cutoff}
            ''')
            
            self.conn.commit()
            logger.info(f"✓ Cleaned up data older than {days} days")
    
    def backup_database(self, backup_path: str = None):
        """Create database backup"""
        if backup_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"{self.db_path}.backup_{timestamp}"
        
        with self.lock:
            # Use SQLite backup API
            backup_conn = sqlite3.connect(backup_path)
            self.conn.backup(backup_conn)
            backup_conn.close()
            logger.info(f"✓ Database backed up to {backup_path}")
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("✓ Database connection closed")