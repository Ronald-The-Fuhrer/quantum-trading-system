"""
Advanced Logging System with colored output and file rotation
"""

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
import os


class ColoredFormatter(logging.Formatter):
    """Custom colored formatter for console output"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def format(self, record):
        # Add color to levelname
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{self.BOLD}{levelname}{self.RESET}"
        
        # Format the message
        result = super().format(record)
        
        # Reset levelname for other handlers
        record.levelname = levelname
        
        return result


def setup_logger(name: str, log_file: str = None, level=logging.INFO,
                console_output: bool = True, file_output: bool = True) -> logging.Logger:
    """
    Setup logger with console and file handlers
    
    Args:
        name: Logger name
        log_file: Log file path (default: logs/{name}.log)
        level: Logging level
        console_output: Enable console output
        file_output: Enable file output
    
    Returns:
        Configured logger
    """
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers
    logger.handlers = []
    
    # Create logs directory
    if file_output:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        if log_file is None:
            log_file = os.path.join(log_dir, f'{name}.log')
    
    # Console handler with colors
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_formatter = ColoredFormatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # File handler with rotation
    if file_output:
        # Rotating file handler (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Error log file (errors only)
        error_log = log_file.replace('.log', '_errors.log')
        error_handler = RotatingFileHandler(
            error_log,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


def setup_trading_logger(log_trades: bool = True, log_performance: bool = True) -> dict:
    """
    Setup specialized loggers for trading system
    
    Returns:
        Dictionary of loggers
    """
    loggers = {}
    
    # Main system logger
    loggers['main'] = setup_logger('QuantumTrading', 'logs/system.log')
    
    # Trade logger
    if log_trades:
        loggers['trades'] = setup_logger(
            'Trades',
            'logs/trades.log',
            console_output=False
        )
    
    # Performance logger
    if log_performance:
        loggers['performance'] = setup_logger(
            'Performance',
            'logs/performance.log',
            console_output=False
        )
    
    # Risk logger
    loggers['risk'] = setup_logger(
        'Risk',
        'logs/risk.log',
        console_output=False
    )
    
    # Strategy logger
    loggers['strategy'] = setup_logger(
        'Strategy',
        'logs/strategy.log',
        console_output=False
    )
    
    # Execution logger
    loggers['execution'] = setup_logger(
        'Execution',
        'logs/execution.log',
        console_output=False
    )
    
    # Data logger
    loggers['data'] = setup_logger(
        'Data',
        'logs/data.log',
        level=logging.WARNING,
        console_output=False
    )
    
    return loggers


class TradeLogger:
    """Specialized logger for trade events"""
    
    def __init__(self):
        self.logger = setup_logger('TradeLogger', 'logs/trades.log', console_output=False)
    
    def log_trade(self, trade_data: dict):
        """Log a trade event"""
        self.logger.info(
            f"TRADE | {trade_data.get('action')} {trade_data.get('quantity')} "
            f"{trade_data.get('ticker')} @ ${trade_data.get('price'):.2f} | "
            f"Strategy: {trade_data.get('strategy')} | "
            f"Confidence: {trade_data.get('confidence'):.2%}"
        )
    
    def log_order_filled(self, order_id: str, fill_price: float, quantity: float):
        """Log order fill"""
        self.logger.info(f"ORDER FILLED | ID: {order_id} | Price: ${fill_price:.2f} | Qty: {quantity}")
    
    def log_order_rejected(self, order_id: str, reason: str):
        """Log order rejection"""
        self.logger.error(f"ORDER REJECTED | ID: {order_id} | Reason: {reason}")


class PerformanceLogger:
    """Specialized logger for performance metrics"""
    
    def __init__(self):
        self.logger = setup_logger('PerformanceLogger', 'logs/performance.log', console_output=False)
    
    def log_daily_summary(self, date: str, metrics: dict):
        """Log daily performance summary"""
        self.logger.info(
            f"DAILY | {date} | "
            f"PnL: ${metrics.get('pnl', 0):.2f} | "
            f"Return: {metrics.get('return', 0):.2%} | "
            f"Sharpe: {metrics.get('sharpe', 0):.2f} | "
            f"Trades: {metrics.get('trades', 0)}"
        )
    
    def log_portfolio_snapshot(self, value: float, positions: int, cash: float):
        """Log portfolio snapshot"""
        self.logger.info(
            f"PORTFOLIO | Value: ${value:,.2f} | "
            f"Positions: {positions} | Cash: ${cash:,.2f}"
        )


# Create global loggers
def get_logger(name: str = 'QuantumTrading') -> logging.Logger:
    """Get or create logger"""
    return logging.getLogger(name)