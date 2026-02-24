"""
LOSS PREVENTION SYSTEM v1.0 - The Guardian
═══════════════════════════════════════════════════════════════════════════════

This module's ONLY job: PREVENT RED DAYS

Multiple layers of protection:
1. PRE-TRADE GUARDIAN - Block bad trades before they happen
2. POSITION GUARDIAN - Monitor every position tick-by-tick  
3. PORTFOLIO GUARDIAN - Watch overall portfolio health
4. TIME GUARDIAN - Ensure we're flat before close
5. RECOVERY MODE - When down, shift to ultra-conservative

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
from collections import deque

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5))

def get_eastern_time() -> datetime:
    return datetime.now(EST)


class LossPreventionSystem:
    """Multi-layer loss prevention guardian"""
    
    def __init__(self, config: Dict):
        self.config = config
        
        # Thresholds
        self.max_daily_loss_dollars = config.get('daily_loss_limit_dollars', 3)
        self.max_daily_loss_pct = config.get('daily_loss_limit_pct', 0.006)
        self.warning_threshold_pct = 0.003  # Warn at 0.3% loss
        self.recovery_threshold_pct = -0.002  # Enter recovery mode at -0.2%
        
        # State
        self.day_start_value = None
        self.high_water_mark = None
        self.low_water_mark = None
        self.recovery_mode = False
        self.trading_halted = False
        self.halt_reason = None
        
        # Tracking
        self.pnl_history = deque(maxlen=100)
        self.trade_results = []  # Today's trade results
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        
        # Position tracking
        self.position_alerts = {}  # ticker -> alert level
        
        logger.info("LossPreventionSystem initialized")
    
    def initialize_day(self, portfolio_value: float):
        """Initialize for new trading day"""
        self.day_start_value = portfolio_value
        self.high_water_mark = portfolio_value
        self.low_water_mark = portfolio_value
        self.recovery_mode = False
        self.trading_halted = False
        self.halt_reason = None
        self.trade_results = []
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.position_alerts = {}
        
        logger.info(f"Loss Prevention initialized: ${portfolio_value:,.2f}")
    
    def update(self, current_value: float, positions: Dict) -> Dict:
        """
        Main update loop - check all protection layers
        Returns action recommendations
        """
        if self.day_start_value is None:
            return {'action': 'CONTINUE', 'alerts': []}
        
        # Update water marks
        self.high_water_mark = max(self.high_water_mark, current_value)
        self.low_water_mark = min(self.low_water_mark, current_value)
        
        # Calculate P&L
        daily_pnl = current_value - self.day_start_value
        daily_pnl_pct = daily_pnl / self.day_start_value
        drawdown_from_high = (self.high_water_mark - current_value) / self.high_water_mark
        
        self.pnl_history.append({
            'time': datetime.now(),
            'value': current_value,
            'pnl': daily_pnl,
            'pnl_pct': daily_pnl_pct
        })
        
        alerts = []
        action = 'CONTINUE'
        
        # === LAYER 1: HALT CHECK ===
        if self.trading_halted:
            return {
                'action': 'HALTED',
                'reason': self.halt_reason,
                'alerts': [{'level': 'CRITICAL', 'message': f'Trading halted: {self.halt_reason}'}]
            }
        
        # === LAYER 2: DAILY LOSS LIMIT ===
        if daily_pnl <= -self.max_daily_loss_dollars:
            self.trading_halted = True
            self.halt_reason = f"Daily loss limit (${self.max_daily_loss_dollars})"
            return {
                'action': 'HALT_AND_LIQUIDATE',
                'reason': self.halt_reason,
                'alerts': [{'level': 'CRITICAL', 'message': f'DAILY LOSS LIMIT HIT: ${daily_pnl:.2f}'}]
            }
        
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            self.trading_halted = True
            self.halt_reason = f"Daily loss limit ({self.max_daily_loss_pct*100:.1f}%)"
            return {
                'action': 'HALT_AND_LIQUIDATE',
                'reason': self.halt_reason,
                'alerts': [{'level': 'CRITICAL', 'message': f'DAILY LOSS LIMIT HIT: {daily_pnl_pct*100:.2f}%'}]
            }
        
        # === LAYER 3: RECOVERY MODE CHECK ===
        if daily_pnl_pct <= self.recovery_threshold_pct and not self.recovery_mode:
            self.recovery_mode = True
            alerts.append({
                'level': 'WARNING',
                'message': f'RECOVERY MODE ACTIVATED: {daily_pnl_pct*100:.2f}%'
            })
            logger.warning(f"🛡️ RECOVERY MODE: P&L at {daily_pnl_pct*100:.2f}%")
        
        # Exit recovery mode if we're back to green
        if daily_pnl_pct >= 0.001 and self.recovery_mode:
            self.recovery_mode = False
            alerts.append({
                'level': 'INFO',
                'message': 'Recovery mode deactivated - back to green'
            })
            logger.info("✅ Exited recovery mode - back to green")
        
        # === LAYER 4: DRAWDOWN CHECK ===
        if drawdown_from_high >= 0.015:  # 1.5% drawdown from high
            alerts.append({
                'level': 'WARNING',
                'message': f'Drawdown alert: {drawdown_from_high*100:.2f}% from high'
            })
            action = 'REDUCE_EXPOSURE'
        
        # === LAYER 5: CONSECUTIVE LOSS CHECK ===
        if self.consecutive_losses >= 3:
            alerts.append({
                'level': 'WARNING',
                'message': f'{self.consecutive_losses} consecutive losses - cooling off'
            })
            action = 'PAUSE_ENTRIES'
        
        # === LAYER 6: TIME-BASED CHECKS ===
        et = get_eastern_time()
        
        # Warning 30 min before close
        if et.time() >= dtime(15, 30) and positions:
            alerts.append({
                'level': 'INFO',
                'message': f'30 min to close with {len(positions)} positions'
            })
        
        # === LAYER 7: POSITION-LEVEL CHECKS ===
        for ticker, pos in positions.items():
            pos_alerts = self._check_position(ticker, pos, daily_pnl_pct)
            alerts.extend(pos_alerts)
        
        return {
            'action': action,
            'recovery_mode': self.recovery_mode,
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'drawdown': drawdown_from_high,
            'consecutive_losses': self.consecutive_losses,
            'alerts': alerts
        }
    
    def _check_position(self, ticker: str, pos: Dict, daily_pnl_pct: float) -> List[Dict]:
        """Check individual position health"""
        alerts = []
        
        entry_price = pos.get('entry_price', 0)
        current_price = pos.get('current_price', 0)
        
        if entry_price <= 0:
            return alerts
        
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Track alert levels
        current_alert = self.position_alerts.get(ticker, 0)
        
        # Progressive alerts
        if pnl_pct <= -0.02 and current_alert < 3:  # -2%
            self.position_alerts[ticker] = 3
            alerts.append({
                'level': 'CRITICAL',
                'message': f'{ticker}: DOWN {pnl_pct*100:.1f}% - FORCE EXIT',
                'action': 'FORCE_EXIT',
                'ticker': ticker
            })
        elif pnl_pct <= -0.015 and current_alert < 2:  # -1.5%
            self.position_alerts[ticker] = 2
            alerts.append({
                'level': 'WARNING',
                'message': f'{ticker}: DOWN {pnl_pct*100:.1f}% - EXIT RECOMMENDED',
                'action': 'EXIT',
                'ticker': ticker
            })
        elif pnl_pct <= -0.01 and current_alert < 1:  # -1%
            self.position_alerts[ticker] = 1
            alerts.append({
                'level': 'INFO',
                'message': f'{ticker}: DOWN {pnl_pct*100:.1f}% - MONITORING',
                'ticker': ticker
            })
        
        # If in recovery mode, tighter thresholds
        if self.recovery_mode and pnl_pct <= -0.008:
            alerts.append({
                'level': 'WARNING',
                'message': f'{ticker}: Recovery mode - exit at {pnl_pct*100:.1f}%',
                'action': 'EXIT',
                'ticker': ticker
            })
        
        return alerts
    
    def record_trade_result(self, pnl: float):
        """Record a completed trade result"""
        self.trade_results.append(pnl)
        
        if pnl >= 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        
        logger.info(f"Trade recorded: ${pnl:+.2f} | Streak: W{self.consecutive_wins}/L{self.consecutive_losses}")
    
    def can_enter_trade(self, confidence: float, position_value: float) -> Tuple[bool, str]:
        """Pre-trade guardian - should we allow this entry?"""
        
        # Halted - no trades
        if self.trading_halted:
            return False, "Trading halted"
        
        # Recovery mode - ultra-high bar
        if self.recovery_mode:
            if confidence < 0.92:
                return False, f"Recovery mode: need 92% confidence, got {confidence*100:.0f}%"
            # Smaller positions in recovery
            max_value = self.day_start_value * 0.10 if self.day_start_value else 50
            if position_value > max_value:
                return False, f"Recovery mode: max position ${max_value:.0f}"
        
        # Consecutive losses - pause
        if self.consecutive_losses >= 3:
            return False, f"{self.consecutive_losses} consecutive losses - paused"
        
        # Time check
        et = get_eastern_time()
        if et.time() >= dtime(15, 30):
            return False, "No new entries after 3:30 PM"
        
        if et.time() < dtime(9, 45):
            return False, "No entries before 9:45 AM"
        
        return True, "OK"
    
    def get_position_size_multiplier(self) -> float:
        """Get position size adjustment based on current state"""
        multiplier = 1.0
        
        if self.recovery_mode:
            multiplier *= 0.5  # Half size in recovery
        
        if self.consecutive_losses >= 2:
            multiplier *= 0.7  # Reduce after losses
        
        # Scale down as day progresses
        et = get_eastern_time()
        if et.time() >= dtime(14, 0):
            multiplier *= 0.8
        if et.time() >= dtime(15, 0):
            multiplier *= 0.7
        
        return max(0.3, multiplier)  # Never less than 30%
    
    def get_stop_loss_adjustment(self) -> float:
        """Get stop loss adjustment based on current state"""
        if self.recovery_mode:
            return 0.7  # Tighter stops in recovery (70% of normal)
        
        if self.consecutive_losses >= 2:
            return 0.8  # Tighter after losses
        
        return 1.0
    
    def should_force_exit_all(self) -> Tuple[bool, str]:
        """Check if we should force exit all positions"""
        et = get_eastern_time()
        
        # Force exit at 3:55 PM
        if et.time() >= dtime(15, 55):
            return True, "Market close imminent"
        
        # Force exit if halted
        if self.trading_halted:
            return True, self.halt_reason
        
        return False, ""
    
    def get_status_summary(self) -> Dict:
        """Get current loss prevention status"""
        daily_pnl = 0
        daily_pnl_pct = 0
        
        if self.pnl_history:
            latest = self.pnl_history[-1]
            daily_pnl = latest['pnl']
            daily_pnl_pct = latest['pnl_pct']
        
        return {
            'recovery_mode': self.recovery_mode,
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'consecutive_losses': self.consecutive_losses,
            'consecutive_wins': self.consecutive_wins,
            'trades_today': len(self.trade_results),
            'high_water_mark': self.high_water_mark,
            'low_water_mark': self.low_water_mark
        }
