"""
Portfolio Manager - Position tracking with LIVE Alpaca sync
FIXED VERSION - Always fetches real data from Alpaca broker
"""
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False
    logger.warning("Alpaca API not available")


class PortfolioManager:
    """Portfolio position tracking with LIVE broker sync"""
    
    def __init__(self, config: Dict, db, risk_manager):
        self.config = config
        self.db = db
        self.risk_manager = risk_manager
        self.broker = None
        self._cached_account = None
        self._cache_time = None
        self._cache_duration = 5  # Cache for 5 seconds to avoid rate limits
        
        # Initialize Alpaca connection
        if HAS_ALPACA and config.get('alpaca_key'):
            try:
                self.broker = tradeapi.REST(
                    config['alpaca_key'],
                    config['alpaca_secret'],
                    config.get('alpaca_url', 'https://paper-api.alpaca.markets'),
                    api_version='v2'
                )
                # Test connection and get initial capital
                account = self.broker.get_account()
                self.initial_capital = float(account.equity)
                logger.info(f"✓ Connected to Alpaca | Account Value: ${self.initial_capital:,.2f}")
            except Exception as e:
                logger.error(f"Failed to connect to Alpaca: {e}")
                self.broker = None
                self.initial_capital = config.get('initial_capital', 100000)
        else:
            self.initial_capital = config.get('initial_capital', 100000)
            logger.warning("No broker connected - using config initial_capital")
        
        # Track peak for drawdown calculation
        self.peak_value = self.initial_capital
    
    def _get_account(self) -> Optional[object]:
        """Get Alpaca account with caching to avoid rate limits"""
        if not self.broker:
            return None
        
        now = datetime.now()
        
        # Return cached if still valid
        if self._cached_account and self._cache_time:
            if (now - self._cache_time).seconds < self._cache_duration:
                return self._cached_account
        
        try:
            self._cached_account = self.broker.get_account()
            self._cache_time = now
            return self._cached_account
        except Exception as e:
            logger.error(f"Error fetching Alpaca account: {e}")
            return self._cached_account  # Return stale cache if available
    
    def get_portfolio_value(self) -> float:
        """Get REAL portfolio value from Alpaca"""
        if self.broker:
            try:
                account = self._get_account()
                if account:
                    value = float(account.equity)
                    # Update peak for drawdown tracking
                    if value > self.peak_value:
                        self.peak_value = value
                    return value
            except Exception as e:
                logger.error(f"Error getting portfolio value: {e}")
        
        # Fallback to config value
        return self.config.get('initial_capital', 100000)
    
    def get_cash(self) -> float:
        """Get REAL cash balance from Alpaca"""
        if self.broker:
            try:
                account = self._get_account()
                if account:
                    return float(account.cash)
            except Exception as e:
                logger.error(f"Error getting cash balance: {e}")
        
        return self.config.get('initial_capital', 100000)
    
    def get_buying_power(self) -> float:
        """Get buying power from Alpaca"""
        if self.broker:
            try:
                account = self._get_account()
                if account:
                    return float(account.buying_power)
            except Exception as e:
                logger.error(f"Error getting buying power: {e}")
        
        return self.get_cash()
    
    def get_positions(self) -> Dict:
        """Get REAL positions from Alpaca"""
        positions = {}
        
        if self.broker:
            try:
                alpaca_positions = self.broker.list_positions()
                for pos in alpaca_positions:
                    positions[pos.symbol] = {
                        'ticker': pos.symbol,
                        'quantity': float(pos.qty),
                        'entry_price': float(pos.avg_entry_price),
                        'current_price': float(pos.current_price),
                        'market_value': float(pos.market_value),
                        'unrealized_pnl': float(pos.unrealized_pl),
                        'unrealized_pnl_pct': float(pos.unrealized_plpc) * 100,
                        'side': pos.side
                    }
            except Exception as e:
                logger.error(f"Error fetching positions: {e}")
        
        return positions
    
    def get_position(self, ticker: str) -> Optional[Dict]:
        """Get a specific position from Alpaca"""
        if self.broker:
            try:
                pos = self.broker.get_position(ticker)
                return {
                    'ticker': pos.symbol,
                    'quantity': float(pos.qty),
                    'entry_price': float(pos.avg_entry_price),
                    'current_price': float(pos.current_price),
                    'market_value': float(pos.market_value),
                    'unrealized_pnl': float(pos.unrealized_pl),
                    'side': pos.side
                }
            except Exception as e:
                # Position doesn't exist
                logger.debug(f"No position found for {ticker}")
                return None
        return None
    
    def has_position(self, ticker: str) -> bool:
        """Check if we have a position in a ticker"""
        return self.get_position(ticker) is not None
    
    def get_position_value(self, ticker: str) -> float:
        """Get the market value of a specific position"""
        pos = self.get_position(ticker)
        if pos:
            return pos['market_value']
        return 0.0
    
    def add_position(self, ticker: str, quantity: float, price: float, 
                    strategy: str, stop_loss: float, take_profit: float):
        """Track a new position (actual order is placed by execution_engine)"""
        logger.info(f"Position added: {quantity} {ticker} @ ${price:.2f} | Strategy: {strategy}")
        
        # Log to database
        self.db.log_position({
            'ticker': ticker,
            'quantity': quantity,
            'entry_price': price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'strategy': strategy
        })
    
    def remove_position(self, ticker: str, exit_price: float) -> float:
        """Track position removal and calculate PnL"""
        pos = self.get_position(ticker)
        if pos:
            pnl = (exit_price - pos['entry_price']) * pos['quantity']
            logger.info(f"Position closed: {ticker} | PnL: ${pnl:.2f}")
            return pnl
        return 0.0
    
    def update_portfolio(self):
        """Update portfolio snapshot in database"""
        try:
            portfolio_value = self.get_portfolio_value()
            cash = self.get_cash()
            positions = self.get_positions()
            positions_value = sum(p.get('market_value', 0) for p in positions.values())
            
            # Log to database
            self.db.log_portfolio_snapshot(
                timestamp=datetime.now(),
                total_value=portfolio_value,
                cash=cash,
                positions_value=positions_value,
                num_positions=len(positions)
            )
            
            logger.debug(f"Portfolio updated: ${portfolio_value:,.2f} | {len(positions)} positions")
            
        except Exception as e:
            logger.error(f"Error updating portfolio: {e}")
    
    def get_drawdown(self) -> float:
        """Calculate current drawdown from peak"""
        current_value = self.get_portfolio_value()
        
        if current_value > self.peak_value:
            self.peak_value = current_value
            return 0.0
        
        if self.peak_value > 0:
            drawdown = (self.peak_value - current_value) / self.peak_value
            return drawdown
        
        return 0.0
    
    def get_account_summary(self) -> Dict:
        """Get complete account summary"""
        if self.broker:
            try:
                account = self._get_account()
                positions = self.get_positions()
                
                return {
                    'equity': float(account.equity),
                    'cash': float(account.cash),
                    'buying_power': float(account.buying_power),
                    'portfolio_value': float(account.portfolio_value),
                    'positions_count': len(positions),
                    'positions': positions,
                    'initial_capital': self.initial_capital,
                    'total_return': (float(account.equity) - self.initial_capital) / self.initial_capital,
                    'drawdown': self.get_drawdown(),
                    'peak_value': self.peak_value
                }
            except Exception as e:
                logger.error(f"Error getting account summary: {e}")
        
        return {
            'equity': self.config.get('initial_capital', 100000),
            'cash': self.config.get('initial_capital', 100000),
            'positions_count': 0,
            'positions': {}
        }
    
    def save_state(self):
        """Save current portfolio state to database"""
        try:
            positions = self.get_positions()
            for ticker, pos in positions.items():
                self.db.log_position(pos)
            logger.info(f"Saved state for {len(positions)} positions")
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def close_all_positions(self) -> bool:
        """Close all positions (emergency function)"""
        if not self.broker:
            logger.error("No broker connection - cannot close positions")
            return False
        
        try:
            # Alpaca has a convenient method for this
            self.broker.close_all_positions()
            logger.info("✓ All positions closed")
            return True
        except Exception as e:
            logger.error(f"Error closing all positions: {e}")
            return False
    
    def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        if not self.broker:
            return False
        
        try:
            self.broker.cancel_all_orders()
            logger.info("✓ All orders cancelled")
            return True
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            return False