"""
PDT TRACKER v1.0 - Pattern Day Trader Compliance
═══════════════════════════════════════════════════════════════════════════════

CRITICAL RULES:
- Accounts under $25,000 are limited to 3 day trades per 5 business days
- A "day trade" = buying AND selling the same stock on the same calendar day
- We track all trades and PREVENT sells that would violate PDT

STRATEGY:
- Default to SWING TRADING (hold overnight, no day trade)
- Only use day trades for EMERGENCY exits (catastrophic stop)
- Preserve day trades for true emergencies
- Hold losing positions until next day rather than violate PDT

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import json
import os

logger = logging.getLogger(__name__)


class PDTTracker:
    """Tracks day trades and prevents PDT violations"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.account_value = config.get('initial_capital', 500)
        self.pdt_threshold = 25000  # $25,000 PDT threshold
        
        # Day trade tracking
        self.day_trades = []  # List of {date, ticker, buy_time, sell_time}
        self.max_day_trades = 3  # Max 3 per 5 business days
        self.lookback_days = 5  # Rolling 5 business days
        
        # Position tracking for same-day detection
        self.todays_buys = {}  # ticker -> buy_time
        self.position_buy_dates = {}  # ticker -> date when bought
        
        # State file for persistence
        self.state_file = config.get('pdt_state_file', 'data/pdt_state.json')
        
        # Load persisted state
        self._load_state()
        
        logger.info(f"PDTTracker initialized | Account: ${self.account_value:,.2f} | "
                   f"Day trades used: {self.get_day_trades_used()}/3")
    
    def _load_state(self):
        """Load persisted PDT state"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.day_trades = state.get('day_trades', [])
                    self.position_buy_dates = state.get('position_buy_dates', {})
                    # Convert date strings back to dates
                    for trade in self.day_trades:
                        if isinstance(trade.get('date'), str):
                            trade['date'] = datetime.strptime(trade['date'], '%Y-%m-%d').date()
                    for ticker, date_str in self.position_buy_dates.items():
                        if isinstance(date_str, str):
                            self.position_buy_dates[ticker] = datetime.strptime(date_str, '%Y-%m-%d').date()
                    logger.info(f"Loaded PDT state: {len(self.day_trades)} day trades tracked")
        except Exception as e:
            logger.warning(f"Could not load PDT state: {e}")
    
    def _save_state(self):
        """Save PDT state to disk
        v10.0 FIX: Convert ALL date/datetime fields, not just 'date'.
        Bug: 'buy_date' and 'sell_date' were date objects not converted → JSON error.
        """
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            
            def _serialize_date(v):
                """Convert date/datetime to string safely"""
                if isinstance(v, (date, datetime)):
                    return v.isoformat()
                return v
            
            state = {
                'day_trades': [
                    {k: _serialize_date(v) for k, v in t.items()}
                    for t in self.day_trades
                ],
                'position_buy_dates': {
                    k: _serialize_date(v)
                    for k, v in self.position_buy_dates.items()
                }
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save PDT state: {e}")
    
    def update_account_value(self, value: float):
        """Update account value to check if PDT applies"""
        self.account_value = value
    
    def is_pdt_restricted(self) -> bool:
        """Check if account is subject to PDT rules"""
        return self.account_value < self.pdt_threshold
    
    def get_day_trades_used(self) -> int:
        """Get number of day trades used in rolling 5 business days"""
        if not self.is_pdt_restricted():
            return 0
        
        today = date.today()
        cutoff = today - timedelta(days=7)  # Extra buffer for weekends
        
        # Count day trades in the window
        count = 0
        business_days_checked = 0
        check_date = today
        
        while business_days_checked < self.lookback_days and check_date >= cutoff:
            if check_date.weekday() < 5:  # Monday-Friday
                for trade in self.day_trades:
                    trade_date = trade.get('date')
                    if isinstance(trade_date, str):
                        trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
                    if trade_date == check_date:
                        count += 1
                business_days_checked += 1
            check_date -= timedelta(days=1)
        
        return count
    
    def get_day_trades_remaining(self) -> int:
        """Get remaining day trades available"""
        if not self.is_pdt_restricted():
            return 999  # Unlimited
        return max(0, self.max_day_trades - self.get_day_trades_used())
    
    def record_buy(self, ticker: str, buy_time: datetime = None):
        """Record a buy for same-day sell detection"""
        buy_time = buy_time or datetime.now()
        buy_date = buy_time.date()
        
        self.todays_buys[ticker] = buy_time
        self.position_buy_dates[ticker] = buy_date
        
        logger.info(f"📝 PDT: Recorded BUY {ticker} on {buy_date}")
        self._save_state()
    
    def can_sell_today(self, ticker: str) -> Tuple[bool, str]:
        """
        Check if selling this ticker TODAY would be a day trade.
        Returns (can_sell, reason)
        """
        # If not PDT restricted, always allow
        if not self.is_pdt_restricted():
            return True, "Account above PDT threshold"
        
        today = date.today()
        buy_date = self.position_buy_dates.get(ticker)
        
        # If we don't have a buy date recorded, assume it's from a previous day (allow sell)
        if buy_date is None:
            return True, "No same-day buy recorded"
        
        # Convert if string
        if isinstance(buy_date, str):
            buy_date = datetime.strptime(buy_date, '%Y-%m-%d').date()
        
        # If bought on a different day, not a day trade
        if buy_date != today:
            return True, f"Bought on {buy_date}, not same day"
        
        # This WOULD be a day trade - check if we have any remaining
        remaining = self.get_day_trades_remaining()
        
        if remaining > 0:
            return True, f"Day trade allowed ({remaining} remaining)"
        else:
            return False, f"PDT BLOCKED: 0 day trades remaining (bought today)"
    
    def would_be_day_trade(self, ticker: str) -> bool:
        """Check if selling this ticker would be a day trade"""
        if not self.is_pdt_restricted():
            return False
        
        today = date.today()
        buy_date = self.position_buy_dates.get(ticker)
        
        if buy_date is None:
            return False
        
        if isinstance(buy_date, str):
            buy_date = datetime.strptime(buy_date, '%Y-%m-%d').date()
        
        return buy_date == today
    
    def record_sell(self, ticker: str, sell_time: datetime = None):
        """Record a sell and track if it was a day trade"""
        sell_time = sell_time or datetime.now()
        sell_date = sell_time.date()
        
        # Check if this is a day trade
        buy_date = self.position_buy_dates.get(ticker)
        if buy_date:
            if isinstance(buy_date, str):
                buy_date = datetime.strptime(buy_date, '%Y-%m-%d').date()
            
            if buy_date == sell_date:
                # This is a day trade!
                self.day_trades.append({
                    'date': sell_date,
                    'ticker': ticker,
                    'buy_date': buy_date,
                    'sell_date': sell_date
                })
                logger.warning(f"⚠️ PDT: DAY TRADE recorded for {ticker} | "
                             f"{self.get_day_trades_used()}/{self.max_day_trades} used")
        
        # Clear tracking
        if ticker in self.todays_buys:
            del self.todays_buys[ticker]
        if ticker in self.position_buy_dates:
            del self.position_buy_dates[ticker]
        
        self._save_state()
    
    def cleanup_old_trades(self):
        """Remove day trades older than 5 business days"""
        today = date.today()
        cutoff = today - timedelta(days=10)  # Extra buffer
        
        self.day_trades = [
            t for t in self.day_trades
            if (t.get('date') if isinstance(t.get('date'), date) 
                else datetime.strptime(t['date'], '%Y-%m-%d').date()) >= cutoff
        ]
        self._save_state()
    
    def get_sellable_positions(self, positions: Dict) -> Dict:
        """
        Filter positions to only those that can be sold without PDT violation.
        Used to show user which positions are 'free' to sell.
        """
        sellable = {}
        for ticker, pos in positions.items():
            can_sell, reason = self.can_sell_today(ticker)
            if can_sell:
                sellable[ticker] = pos
                sellable[ticker]['pdt_status'] = 'SELLABLE'
            else:
                # Include but mark as blocked
                sellable[ticker] = pos.copy()
                sellable[ticker]['pdt_status'] = 'PDT_BLOCKED'
                sellable[ticker]['pdt_reason'] = reason
        return sellable
    
    def get_status(self) -> Dict:
        """Get current PDT status"""
        return {
            'pdt_restricted': self.is_pdt_restricted(),
            'account_value': self.account_value,
            'pdt_threshold': self.pdt_threshold,
            'day_trades_used': self.get_day_trades_used(),
            'day_trades_remaining': self.get_day_trades_remaining(),
            'max_day_trades': self.max_day_trades,
            'positions_bought_today': list(self.todays_buys.keys()),
            'recent_day_trades': self.day_trades[-5:] if self.day_trades else []
        }
    
    def should_allow_emergency_exit(self, ticker: str, pnl_pct: float) -> Tuple[bool, str]:
        """
        Determine if we should use a precious day trade for emergency exit.
        Only for catastrophic situations.
        """
        # If not a day trade, always allow
        if not self.would_be_day_trade(ticker):
            return True, "Not a day trade"
        
        remaining = self.get_day_trades_remaining()
        
        # Catastrophic loss (-5% or more) - use day trade
        if pnl_pct <= -0.05:
            if remaining > 0:
                return True, f"EMERGENCY: Catastrophic loss {pnl_pct*100:.1f}%"
            else:
                return False, "Would violate PDT even for emergency"
        
        # Significant loss (-3% to -5%) - use day trade if we have 2+ remaining
        if pnl_pct <= -0.03:
            if remaining >= 2:
                return True, f"EMERGENCY: Significant loss {pnl_pct*100:.1f}%"
            else:
                return False, "Preserving day trades for bigger emergencies"
        
        # Normal loss - do NOT use day trade, hold overnight
        return False, "Hold overnight - not worth using day trade"
    
    def initialize_positions(self, positions: Dict):
        """
        Initialize tracking for existing positions.
        Called on bot startup to sync with broker positions.
        """
        today = date.today()
        
        for ticker, pos in positions.items():
            # If we don't have this position tracked, assume it's from a previous day
            if ticker not in self.position_buy_dates:
                # Assume bought yesterday so we CAN sell today
                self.position_buy_dates[ticker] = today - timedelta(days=1)
                logger.info(f"📝 PDT: Initialized {ticker} as previous-day position (sellable)")
        
        self._save_state()
