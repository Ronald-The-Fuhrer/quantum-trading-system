"""
REGIME DETECTOR v2.1 - Fixed Initialization Bug
═══════════════════════════════════════════════════════════════════════════════

CRITICAL FIX: Don't trigger CRASH on startup!
- Start in NEUTRAL mode
- Require multiple confirmations before changing to CRASH
- Only trigger CRASH on ACTUAL -2.5% drops, not data fetch issues

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from collections import deque

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Smart market regime detection - FIXED initialization"""
    
    def __init__(self, config: Dict, data_manager=None):
        self.config = config
        self.data_manager = data_manager
        
        # Thresholds - ONLY trigger CRASH on severe drops
        self.crash_threshold = -0.025  # -2.5% for CRASH
        self.crash_exit_threshold = -0.015  # Exit CRASH when better than -1.5%
        self.risk_off_threshold = -0.015  # -1.5% for RISK_OFF
        self.risk_on_threshold = 0.01  # +1% for RISK_ON
        
        # State - START IN NEUTRAL, NOT CRASH
        self.current_regime = 'NEUTRAL'
        self.regime_confidence = 0.5
        self.regime_start_time = datetime.now()
        self.last_regime_change = datetime.now()
        
        # CRITICAL: Track if we've initialized properly
        self.initialized = False
        self.initialization_readings = 0
        self.min_readings_before_crash = 5  # Need 5 readings before we can trigger CRASH
        
        # History for smoothing
        self.spy_history = deque(maxlen=30)
        self.regime_history = deque(maxlen=10)
        
        # Hysteresis - minimum time between regime changes
        self.min_regime_duration = timedelta(minutes=15)
        
        # Reference prices
        self.day_open_spy = None
        self.previous_close_spy = None
        
        logger.info("RegimeDetector v2.1 initialized - STARTS IN NEUTRAL")
    
    def update(self, spy_price: float = None, vix: float = None) -> Tuple[str, float, bool]:
        """
        Update regime detection
        
        Returns: (regime, confidence, changed)
        """
        try:
            # Get SPY data if not provided
            if spy_price is None:
                spy_data = self._fetch_spy_data()
                if spy_data:
                    spy_price = spy_data.get('price', 0)
                    if self.day_open_spy is None:
                        self.day_open_spy = spy_data.get('open', spy_price)
                    if self.previous_close_spy is None:
                        self.previous_close_spy = spy_data.get('previous_close', spy_price)
                else:
                    # Can't get data - STAY IN CURRENT REGIME
                    logger.debug("Cannot fetch SPY data - staying in current regime")
                    return self.current_regime, self.regime_confidence, False
            
            if spy_price is None or spy_price <= 0:
                return self.current_regime, self.regime_confidence, False
            
            # Track initialization
            self.initialization_readings += 1
            
            # Store history
            self.spy_history.append({
                'price': spy_price,
                'time': datetime.now()
            })
            
            # Calculate day change
            if self.previous_close_spy and self.previous_close_spy > 0:
                day_change_pct = (spy_price - self.previous_close_spy) / self.previous_close_spy
            else:
                # No reference price - assume flat, stay NEUTRAL
                day_change_pct = 0
                logger.debug("No previous close reference - assuming flat")
            
            # Get VIX if not provided
            if vix is None:
                vix = self._fetch_vix()
            vix = vix or 20  # Default VIX
            
            # Log the actual data
            logger.debug(f"Regime data: SPY=${spy_price:.2f}, PrevClose=${self.previous_close_spy or 0:.2f}, Change={day_change_pct*100:.2f}%, VIX={vix:.1f}")
            
            # CRITICAL: Don't allow CRASH until we have enough readings
            if self.initialization_readings < self.min_readings_before_crash:
                if day_change_pct <= self.crash_threshold:
                    logger.warning(f"⚠️ CRASH signal ignored - only {self.initialization_readings}/{self.min_readings_before_crash} readings")
                    # Stay in NEUTRAL or RISK_OFF during initialization
                    if day_change_pct <= self.risk_off_threshold:
                        self.current_regime = 'RISK_OFF'
                        self.regime_confidence = 0.6
                    return self.current_regime, self.regime_confidence, False
            
            # Determine new regime
            new_regime, confidence = self._calculate_regime(day_change_pct, vix)
            
            # Apply hysteresis - don't change too quickly
            time_in_regime = datetime.now() - self.last_regime_change
            
            if new_regime != self.current_regime:
                # Must be in current regime for minimum duration before changing
                if time_in_regime < self.min_regime_duration:
                    # Exception: Always allow immediate change TO crash IF confirmed
                    if new_regime != 'CRASH':
                        logger.debug(f"Regime change to {new_regime} blocked by hysteresis")
                        return self.current_regime, self.regime_confidence, False
                
                # For CRASH, require multiple confirmations
                if new_regime == 'CRASH':
                    if not self._confirm_crash():
                        logger.debug("CRASH not confirmed by history")
                        return self.current_regime, self.regime_confidence, False
                
                # Change regime
                old_regime = self.current_regime
                self.current_regime = new_regime
                self.regime_confidence = confidence
                self.last_regime_change = datetime.now()
                
                logger.warning(f"🔄 REGIME: {old_regime} → {new_regime} ({confidence:.0%}) [Change={day_change_pct*100:.2f}%]")
                return new_regime, confidence, True
            
            # Update confidence
            self.regime_confidence = confidence
            return self.current_regime, confidence, False
            
        except Exception as e:
            logger.error(f"Regime update error: {e}")
            # On error, stay in NEUTRAL, don't go to CRASH
            return 'NEUTRAL', 0.5, False
    
    def _calculate_regime(self, day_change_pct: float, vix: float) -> Tuple[str, float]:
        """Calculate regime based on market data"""
        
        # CRASH detection - only for severe drops
        if day_change_pct <= self.crash_threshold:
            return 'CRASH', 0.95
        
        # If currently in CRASH, need significant recovery to exit
        if self.current_regime == 'CRASH':
            if day_change_pct > self.crash_exit_threshold:
                return 'RISK_OFF', 0.75  # Transition through RISK_OFF
            else:
                return 'CRASH', 0.90  # Stay in CRASH
        
        # VIX-based override - but not immediate CRASH
        if vix > 35:
            return 'RISK_OFF', 0.85  # High VIX = RISK_OFF, not CRASH
        elif vix > 28:
            return 'RISK_OFF', 0.75
        
        # Normal regime detection
        if day_change_pct <= self.risk_off_threshold:
            confidence = min(0.85, 0.60 + abs(day_change_pct) * 10)
            return 'RISK_OFF', confidence
        
        elif day_change_pct >= self.risk_on_threshold:
            confidence = min(0.90, 0.60 + day_change_pct * 10)
            return 'RISK_ON', confidence
        
        else:
            # NEUTRAL - market is flat-ish
            return 'NEUTRAL', 0.70
    
    def _confirm_crash(self) -> bool:
        """Confirm CRASH with multiple readings"""
        if len(self.spy_history) < 3:
            return False  # Not enough history
        
        if not self.previous_close_spy:
            return False  # No reference price
        
        # Check last 3 readings - all must show crash-level drops
        recent = list(self.spy_history)[-3:]
        crash_count = 0
        
        for reading in recent:
            change = (reading['price'] - self.previous_close_spy) / self.previous_close_spy
            if change <= self.crash_threshold:
                crash_count += 1
        
        confirmed = crash_count >= 2  # At least 2 of 3 must confirm
        if not confirmed:
            logger.debug(f"CRASH confirmation failed: {crash_count}/3 readings")
        
        return confirmed
    
    def _fetch_spy_data(self) -> Optional[Dict]:
        """Fetch SPY data"""
        try:
            import yfinance as yf
            spy = yf.Ticker('SPY')
            hist = spy.history(period='2d')
            if len(hist) >= 1:
                return {
                    'price': float(hist['Close'].iloc[-1]),
                    'open': float(hist['Open'].iloc[-1]),
                    'previous_close': float(hist['Close'].iloc[-2]) if len(hist) >= 2 else float(hist['Close'].iloc[-1])
                }
        except Exception as e:
            logger.debug(f"SPY fetch error: {e}")
        return None
    
    def _fetch_vix(self) -> Optional[float]:
        """Fetch VIX level"""
        try:
            import yfinance as yf
            vix = yf.Ticker('^VIX')
            hist = vix.history(period='1d')
            if len(hist) >= 1:
                return float(hist['Close'].iloc[-1])
        except:
            pass
        return None
    
    def initialize_day(self, spy_open: float, spy_prev_close: float):
        """Initialize for new trading day"""
        self.day_open_spy = spy_open
        self.previous_close_spy = spy_prev_close
        self.current_regime = 'NEUTRAL'  # ALWAYS start NEUTRAL
        self.regime_confidence = 0.5
        self.spy_history.clear()
        self.initialization_readings = 0
        logger.info(f"Regime day init: Open=${spy_open:.2f}, PrevClose=${spy_prev_close:.2f} - Starting NEUTRAL")
    
    def get_trading_adjustments(self) -> Dict:
        """Get trading parameter adjustments based on regime"""
        adjustments = {
            'RISK_ON': {
                'allow_entries': True,
                'position_multiplier': 1.2,
                'confidence_threshold': 0.80,
                'max_positions': 5,
                'description': 'Bullish - full trading'
            },
            'NEUTRAL': {
                'allow_entries': True,
                'position_multiplier': 1.0,
                'confidence_threshold': 0.82,
                'max_positions': 4,
                'description': 'Normal conditions'
            },
            'RISK_OFF': {
                'allow_entries': True,  # Still allow but reduced
                'position_multiplier': 0.6,
                'confidence_threshold': 0.85,
                'max_positions': 3,
                'description': 'Cautious - reduced exposure'
            },
            'CRASH': {
                'allow_entries': False,  # No new entries
                'position_multiplier': 0.0,
                'confidence_threshold': 0.95,
                'max_positions': 0,
                'description': 'CRASH - no new entries'
            },
            'RECOVERY': {
                'allow_entries': True,
                'position_multiplier': 0.5,
                'confidence_threshold': 0.88,
                'max_positions': 2,
                'description': 'Recovery - selective entries'
            }
        }
        return adjustments.get(self.current_regime, adjustments['NEUTRAL'])
    
    def get_status(self) -> Dict:
        """Get current regime status"""
        return {
            'regime': self.current_regime,
            'confidence': self.regime_confidence,
            'time_in_regime': (datetime.now() - self.last_regime_change).seconds,
            'readings': self.initialization_readings,
            'adjustments': self.get_trading_adjustments()
        }
