"""
Execution Engine v3.3 - BULLETPROOF EXITS + SINGLE-SHARE POSITION FIX
═══════════════════════════════════════════════════════════════════════════════
v3.3 FIX (Mar 6, 2026):
- Single-share orders (qty=1) now bypass the percentage-of-portfolio cap.
  On a $500 account, 1 share of GOOGL ($300) is 60% of portfolio — but that's
  the minimum possible order. The old 25% cap blocked AVGO, GOOGL, ALB, AMT,
  ADP, AME on Mar 6 even though main.py approved them and we had the cash.
  Multi-share orders still respect the cap. Added 90% cash hard safety.

PRIOR FIXES:
- Added extensive logging to debug exit failures
- EOD uses broker.close_position() for guaranteed closure
- Retry mechanism for failed orders
- Better error messages
═══════════════════════════════════════════════════════════════════════════════
"""
from typing import Dict, Optional, Set
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False


class ExecutionEngine:
    """Order execution engine with bulletproof exits"""
    
    def __init__(self, config: Dict, portfolio_manager, risk_manager, db):
        self.config = config
        self.portfolio = portfolio_manager
        self.risk_manager = risk_manager
        self.db = db
        
        # v10.2 FIX: For $500 accounts buying 1 share at a time, every trade is
        # inherently a large % of portfolio. The percentage guard is meaningful for
        # multi-share orders (preventing over-concentration), but for qty=1 minimum
        # orders, main.py already validated affordability via cash * 0.90.
        # We keep the guard for multi-share orders but allow single-share through.
        self.max_position_pct = max(config.get('max_position_size', 0.20), 0.35)
        self.max_positions = config.get('max_positions', 5)
        self._pending_tickers: Set[str] = set()
        
        self.broker = None
        if HAS_ALPACA and config.get('alpaca_key'):
            try:
                self.broker = tradeapi.REST(
                    config['alpaca_key'],
                    config['alpaca_secret'],
                    config.get('alpaca_url', 'https://paper-api.alpaca.markets'),
                    api_version='v2'
                )
                # Test connection
                account = self.broker.get_account()
                logger.info(f"✓ Alpaca connected | ${float(account.equity):,.2f}")
                self._refresh_pending_orders()
            except Exception as e:
                logger.error(f"Alpaca connection failed: {e}")
                self.broker = None
        else:
            logger.warning("No broker configured - paper trading mode")
    
    def _refresh_pending_orders(self) -> None:
        """Refresh pending orders"""
        self._pending_tickers.clear()
        if self.broker:
            try:
                orders = self.broker.list_orders(status='open')
                for order in orders:
                    if order.side == 'buy':
                        self._pending_tickers.add(order.symbol)
                if self._pending_tickers:
                    logger.info(f"Pending orders: {', '.join(sorted(self._pending_tickers))}")
            except Exception as e:
                logger.error(f"Error refreshing orders: {e}")
    
    def _has_pending_order(self, ticker: str) -> bool:
        """Check for pending buy order"""
        if ticker in self._pending_tickers:
            return True
        if self.broker:
            try:
                orders = self.broker.list_orders(status='open', symbols=[ticker])
                for order in orders:
                    if order.side == 'buy' and order.symbol == ticker:
                        self._pending_tickers.add(ticker)
                        return True
            except Exception as e:
                logger.debug(f"Pending check error {ticker}: {e}")
        return False
    
    def _has_position(self, ticker: str) -> bool:
        """Check if position exists"""
        if self.broker:
            try:
                pos = self.broker.get_position(ticker)
                has_pos = pos is not None and float(pos.qty) > 0
                logger.debug(f"_has_position({ticker}): {has_pos}")
                return has_pos
            except tradeapi.rest.APIError as e:
                if 'position does not exist' in str(e).lower():
                    logger.debug(f"No position for {ticker}")
                    return False
                logger.warning(f"API error checking {ticker}: {e}")
                return False
            except Exception as e:
                logger.error(f"Error checking position {ticker}: {e}")
                return False
        return self.portfolio.has_position(ticker)
    
    def _get_position_count(self) -> int:
        """Get number of open positions"""
        if self.broker:
            try:
                positions = self.broker.list_positions()
                return len(positions)
            except Exception as e:
                logger.error(f"Position count error: {e}")
        return len(self.portfolio.get_positions())

    def execute_exit(self, ticker: str, quantity: float, price: float, reason: str = "") -> Dict:
        """
        Execute exit order with detailed logging
        """
        logger.info(f"[EXIT] {ticker}: qty={quantity}, price=${price:.2f}, reason={reason}")
        
        try:
            # Step 1: Verify position exists
            if not self._has_position(ticker):
                logger.error(f"[EXIT] {ticker}: NO POSITION FOUND - cannot exit")
                return {'success': False, 'pnl': 0, 'error': 'No position found'}
            
            order_id = None
            pnl = 0
            
            if self.broker:
                try:
                    # Step 2: Get actual position data from Alpaca
                    pos = self.broker.get_position(ticker)
                    actual_qty = int(float(pos.qty))
                    entry_price = float(pos.avg_entry_price)
                    current_price = float(pos.current_price)
                    
                    logger.info(f"[EXIT] {ticker}: Alpaca position - qty={actual_qty}, entry=${entry_price:.2f}, current=${current_price:.2f}")
                    
                    # Step 3: Submit sell order
                    logger.info(f"[EXIT] {ticker}: Submitting SELL order for {actual_qty} shares...")
                    
                    order = self.broker.submit_order(
                        symbol=ticker,
                        qty=actual_qty,
                        side='sell',
                        type='market',
                        time_in_force='day'
                    )
                    
                    order_id = order.id
                    pnl = (current_price - entry_price) * actual_qty
                    self._pending_tickers.discard(ticker)
                    
                    logger.info(f"[EXIT] ✅ {ticker}: Order {order_id} submitted | P&L: ${pnl:+,.2f}")
                    
                except tradeapi.rest.APIError as e:
                    error_msg = str(e)
                    logger.error(f"[EXIT] ❌ {ticker}: Alpaca API error - {error_msg}")
                    
                    # If market is closed, try to cancel and note
                    if 'market is closed' in error_msg.lower():
                        logger.error(f"[EXIT] {ticker}: MARKET CLOSED - cannot execute")
                    
                    return {'success': False, 'pnl': 0, 'error': error_msg}
                    
                except Exception as e:
                    logger.error(f"[EXIT] ❌ {ticker}: Unexpected error - {e}")
                    return {'success': False, 'pnl': 0, 'error': str(e)}
            else:
                # Paper trading
                order_id = f"paper_exit_{ticker}_{datetime.now().timestamp()}"
                pnl = self.portfolio.remove_position(ticker, price)
                logger.info(f"[EXIT] ✅ PAPER {ticker}: ${pnl:+,.2f}")
            
            # Log to database
            self.db.log_trade({
                'timestamp': datetime.now(),
                'ticker': ticker,
                'action': 'SELL',
                'quantity': quantity,
                'price': price,
                'strategy': 'exit',
                'reason': reason,
                'pnl': pnl,
                'order_id': order_id
            })
            
            return {'success': True, 'pnl': pnl, 'order_id': order_id}
            
        except Exception as e:
            logger.error(f"[EXIT] ❌ {ticker}: Fatal error - {e}", exc_info=True)
            return {'success': False, 'pnl': 0, 'error': str(e)}
    
    def execute_entry(self, ticker: str, quantity: int, price: float, 
                     strategy: str, direction: int = 1) -> Dict:
        """Execute entry order"""
        logger.info(f"[ENTRY] {ticker}: qty={quantity}, price=${price:.2f}, strategy={strategy}")
        
        try:
            if self._has_position(ticker):
                logger.debug(f"[ENTRY] {ticker}: Already have position")
                return {'success': False, 'error': 'Already have position'}
            
            if self._has_pending_order(ticker):
                logger.debug(f"[ENTRY] {ticker}: Pending order exists")
                return {'success': False, 'error': 'Pending order exists'}
            
            portfolio_value = self.portfolio.get_portfolio_value()
            order_value = quantity * price
            order_pct = order_value / portfolio_value if portfolio_value > 0 else 0
            
            # v10.2 FIX: Allow single-share orders through even if they exceed %
            # On a $500 account, 1 share of GOOGL ($300) = 60% of portfolio.
            # That's unavoidable with single-share trading. main.py already
            # verified we can afford it (cash * 0.90 check).
            # Only enforce percentage cap on multi-share orders where we could
            # actually reduce quantity to stay under the limit.
            if quantity > 1 and order_pct > self.max_position_pct:
                logger.warning(f"[ENTRY] {ticker}: Order too large ({order_pct:.1%})")
                return {'success': False, 'error': 'Order too large'}
            
            # Hard safety: never spend more than 90% of cash on a single position
            cash = self.portfolio.get_cash()
            if order_value > cash * 0.90:
                logger.warning(f"[ENTRY] {ticker}: Exceeds 90% of cash (${order_value:.2f} > ${cash*0.90:.2f})")
                return {'success': False, 'error': 'Exceeds cash limit'}
            
            pos_count = self._get_position_count()
            if pos_count >= self.max_positions:
                logger.warning(f"[ENTRY] {ticker}: Max positions ({pos_count}/{self.max_positions})")
                return {'success': False, 'error': 'Max positions reached'}
            
            order_id = None
            
            if self.broker:
                try:
                    order = self.broker.submit_order(
                        symbol=ticker,
                        qty=quantity,
                        side='buy',
                        type='market',
                        time_in_force='day'
                    )
                    order_id = order.id
                    self._pending_tickers.add(ticker)
                    logger.info(f"[ENTRY] ✅ {ticker}: Order {order_id}")
                    
                except Exception as e:
                    logger.error(f"[ENTRY] ❌ {ticker}: {e}")
                    return {'success': False, 'error': str(e)}
            else:
                order_id = f"paper_entry_{ticker}_{datetime.now().timestamp()}"
                logger.info(f"[ENTRY] ✅ PAPER {ticker}")
            
            # Track position
            stop_loss = price * (1 - self.config.get('stop_loss_pct', 0.015))
            take_profit = price * (1 + self.config.get('take_profit_pct', 0.02))
            self.portfolio.add_position(ticker, quantity, price, strategy, stop_loss, take_profit)
            
            self.db.log_trade({
                'timestamp': datetime.now(),
                'ticker': ticker,
                'action': 'BUY',
                'quantity': quantity,
                'price': price,
                'strategy': strategy,
                'order_id': order_id
            })
            
            return {'success': True, 'order_id': order_id}
            
        except Exception as e:
            logger.error(f"[ENTRY] ❌ {ticker}: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def force_close_position(self, ticker: str) -> Dict:
        """
        Force close a position using Alpaca's close_position API
        More reliable than submit_order for EOD liquidation
        """
        logger.info(f"[FORCE_CLOSE] {ticker}: Attempting forced closure...")
        
        if not self.broker:
            return {'success': False, 'error': 'No broker'}
        
        try:
            # Get position info first
            try:
                pos = self.broker.get_position(ticker)
                entry_price = float(pos.avg_entry_price)
                current_price = float(pos.current_price)
                qty = float(pos.qty)
                pnl = (current_price - entry_price) * qty
            except:
                pnl = 0
            
            # Use Alpaca's close_position - more reliable
            self.broker.close_position(ticker)
            self._pending_tickers.discard(ticker)
            
            logger.info(f"[FORCE_CLOSE] ✅ {ticker}: Closed | P&L: ${pnl:+,.2f}")
            return {'success': True, 'pnl': pnl}
            
        except tradeapi.rest.APIError as e:
            error_msg = str(e)
            logger.error(f"[FORCE_CLOSE] ❌ {ticker}: {error_msg}")
            return {'success': False, 'pnl': 0, 'error': error_msg}
        except Exception as e:
            logger.error(f"[FORCE_CLOSE] ❌ {ticker}: {e}")
            return {'success': False, 'pnl': 0, 'error': str(e)}

    def close_all_positions(self) -> Dict:
        """Emergency close all positions"""
        logger.warning("[CLOSE_ALL] Closing all positions...")
        
        if not self.broker:
            return {'success': False, 'error': 'No broker'}
        
        try:
            self.broker.close_all_positions()
            self._pending_tickers.clear()
            logger.info("[CLOSE_ALL] ✅ All positions closed")
            return {'success': True}
        except Exception as e:
            logger.error(f"[CLOSE_ALL] ❌ {e}")
            return {'success': False, 'error': str(e)}
    
    def cancel_all_orders(self) -> bool:
        """Cancel all pending orders"""
        if not self.broker:
            return False
        try:
            self.broker.cancel_all_orders()
            self._pending_tickers.clear()
            logger.info("✓ All orders cancelled")
            return True
        except Exception as e:
            logger.error(f"Cancel orders error: {e}")
            return False
    
    def get_status(self) -> Dict:
        """Get execution engine status"""
        self._refresh_pending_orders()
        return {
            'positions': self._get_position_count(),
            'pending_orders': len(self._pending_tickers),
            'pending_tickers': list(self._pending_tickers),
            'max_positions': self.max_positions,
            'broker_connected': self.broker is not None
        }
