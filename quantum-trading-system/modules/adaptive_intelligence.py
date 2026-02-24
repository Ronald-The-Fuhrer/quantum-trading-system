"""
ADAPTIVE INTELLIGENCE ENGINE v1.0
═══════════════════════════════════════════════════════════════════════════════

This is NOT about removing filters - it's about SMARTER filters.

CORE PHILOSOPHY:
- When market is UP, we should be IN the market making money
- When market is DOWN, we should be OUT or hedged
- Adapt in REAL-TIME to what's actually happening

INTELLIGENT FEATURES:
1. MARKET PULSE - Read the market's heartbeat every cycle
2. OPPORTUNITY SCANNER - Find the BEST setups, not just any setup
3. ADAPTIVE CONFIDENCE - Adjust thresholds based on conditions
4. MOMENTUM SYNC - Trade WITH the market, not against it
5. SMART POSITION SIZING - Bigger on high-conviction, smaller on uncertain
6. PROFIT LOCK - Progressively tighten stops as profit grows
7. LOSS RECOVERY - Smart recovery mode that still trades

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
from collections import deque
import statistics

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5))

def get_eastern_time() -> datetime:
    return datetime.now(EST)


class AdaptiveIntelligence:
    """The brain that makes smart decisions"""
    
    def __init__(self, config: Dict, data_manager=None):
        self.config = config
        self.data_manager = data_manager
        
        # Market pulse tracking
        self.market_readings = deque(maxlen=60)  # Last 60 readings
        self.spy_prices = deque(maxlen=60)
        self.current_pulse = 'NEUTRAL'  # STRONG_UP, UP, NEUTRAL, DOWN, STRONG_DOWN
        
        # Intraday tracking
        self.day_start_spy = None
        self.day_high_spy = None
        self.day_low_spy = None
        self.last_spy_price = None
        
        # Performance tracking
        self.trades_today = []
        self.wins_today = 0
        self.losses_today = 0
        self.current_streak = 0  # Positive = wins, negative = losses
        
        # Adaptive thresholds
        self.base_confidence = config.get('min_confidence', 0.75)
        self.current_confidence_threshold = self.base_confidence
        
        # Time-based adjustments
        self.morning_session = (dtime(9, 30), dtime(11, 30))  # High activity
        self.midday_session = (dtime(11, 30), dtime(14, 0))   # Lower activity
        self.afternoon_session = (dtime(14, 0), dtime(15, 30)) # Pick up again
        self.eod_session = (dtime(15, 30), dtime(16, 0))      # Close out
        
        logger.info("AdaptiveIntelligence initialized")
    
    def update_market_pulse(self, spy_price: float) -> Dict:
        """
        Read the market's current state and momentum
        Called every cycle to stay in sync
        """
        now = get_eastern_time()
        
        # Initialize day tracking
        if self.day_start_spy is None:
            self.day_start_spy = spy_price
            self.day_high_spy = spy_price
            self.day_low_spy = spy_price
        
        # Update high/low
        self.day_high_spy = max(self.day_high_spy, spy_price)
        self.day_low_spy = min(self.day_low_spy, spy_price)
        
        # Store reading
        self.spy_prices.append(spy_price)
        self.last_spy_price = spy_price
        
        # Calculate metrics
        day_change_pct = (spy_price - self.day_start_spy) / self.day_start_spy if self.day_start_spy else 0
        
        # Short-term momentum (last 5 readings)
        if len(self.spy_prices) >= 5:
            recent_5 = list(self.spy_prices)[-5:]
            short_momentum = (recent_5[-1] - recent_5[0]) / recent_5[0]
        else:
            short_momentum = 0
        
        # Medium-term momentum (last 15 readings)
        if len(self.spy_prices) >= 15:
            recent_15 = list(self.spy_prices)[-15:]
            medium_momentum = (recent_15[-1] - recent_15[0]) / recent_15[0]
        else:
            medium_momentum = day_change_pct
        
        # Determine pulse
        if day_change_pct > 0.005 and short_momentum > 0.001:
            self.current_pulse = 'STRONG_UP'
        elif day_change_pct > 0.002 or short_momentum > 0.0005:
            self.current_pulse = 'UP'
        elif day_change_pct < -0.005 and short_momentum < -0.001:
            self.current_pulse = 'STRONG_DOWN'
        elif day_change_pct < -0.002 or short_momentum < -0.0005:
            self.current_pulse = 'DOWN'
        else:
            self.current_pulse = 'NEUTRAL'
        
        # Adjust confidence threshold based on pulse
        self._adjust_confidence_threshold()
        
        reading = {
            'time': now,
            'spy_price': spy_price,
            'day_change_pct': day_change_pct,
            'short_momentum': short_momentum,
            'medium_momentum': medium_momentum,
            'pulse': self.current_pulse,
            'confidence_threshold': self.current_confidence_threshold
        }
        
        self.market_readings.append(reading)
        
        return reading
    
    def _adjust_confidence_threshold(self):
        """Dynamically adjust confidence threshold"""
        et = get_eastern_time()
        current_time = et.time()
        
        # Start with base
        threshold = self.base_confidence
        
        # Pulse adjustment
        if self.current_pulse == 'STRONG_UP':
            threshold -= 0.05  # Lower bar when market is strong
        elif self.current_pulse == 'UP':
            threshold -= 0.03
        elif self.current_pulse == 'DOWN':
            threshold += 0.03  # Higher bar when market is weak
        elif self.current_pulse == 'STRONG_DOWN':
            threshold += 0.08
        
        # Time of day adjustment
        if self.morning_session[0] <= current_time <= self.morning_session[1]:
            threshold -= 0.02  # More aggressive in morning
        elif self.midday_session[0] <= current_time <= self.midday_session[1]:
            threshold += 0.02  # More cautious at lunch
        elif current_time >= self.eod_session[0]:
            threshold += 0.05  # Very cautious near close
        
        # Streak adjustment
        if self.current_streak >= 2:
            threshold -= 0.02  # On a roll, be a bit more aggressive
        elif self.current_streak <= -2:
            threshold += 0.05  # Losing streak, be more careful
        
        # Clamp to reasonable range
        self.current_confidence_threshold = max(0.65, min(0.92, threshold))
    
    def should_enter(self, signal: Dict) -> Tuple[bool, str, float]:
        """
        Intelligent entry decision
        Returns: (should_enter, reason, position_size_multiplier)
        """
        ticker = signal.get('ticker', '')
        confidence = signal.get('confidence', 0)
        strategy = signal.get('strategy', '')
        
        # Check confidence against adaptive threshold
        if confidence < self.current_confidence_threshold:
            return False, f"Confidence {confidence:.0%} < threshold {self.current_confidence_threshold:.0%}", 0
        
        # Check market pulse alignment
        if self.current_pulse in ['STRONG_DOWN', 'DOWN']:
            # Only mean reversion strategies in down market
            if strategy not in ['mean_reversion', 'volatility']:
                return False, f"Pulse is {self.current_pulse}, only mean_reversion allowed", 0
        
        # Time check
        et = get_eastern_time()
        if et.time() >= dtime(15, 30):
            return False, "Too close to market close", 0
        
        # Calculate position size multiplier based on conviction
        size_mult = 1.0
        
        # Higher confidence = larger position
        if confidence >= 0.90:
            size_mult = 1.3
        elif confidence >= 0.85:
            size_mult = 1.15
        elif confidence >= 0.80:
            size_mult = 1.0
        else:
            size_mult = 0.8
        
        # Adjust for market pulse
        if self.current_pulse == 'STRONG_UP':
            size_mult *= 1.2
        elif self.current_pulse == 'UP':
            size_mult *= 1.1
        elif self.current_pulse == 'DOWN':
            size_mult *= 0.7
        elif self.current_pulse == 'STRONG_DOWN':
            size_mult *= 0.5
        
        # Cap multiplier
        size_mult = min(1.5, max(0.5, size_mult))
        
        return True, f"Pulse:{self.current_pulse}, Conf:{confidence:.0%}", size_mult
    
    def calculate_smart_stops(self, entry_price: float, signal: Dict) -> Dict:
        """
        Calculate intelligent stop-loss and take-profit levels
        Based on volatility, conviction, and market conditions
        """
        confidence = signal.get('confidence', 0.8)
        
        # Base stops from config
        base_sl = self.config.get('stop_loss_pct', 0.012)
        base_tp = self.config.get('take_profit_pct', 0.015)
        
        # Adjust based on market pulse
        if self.current_pulse in ['STRONG_UP', 'UP']:
            # In uptrend, give more room for profit, tighter stop
            sl_pct = base_sl * 0.9
            tp_pct = base_tp * 1.3
        elif self.current_pulse in ['STRONG_DOWN', 'DOWN']:
            # In downtrend, tighter everything
            sl_pct = base_sl * 0.8
            tp_pct = base_tp * 0.8
        else:
            sl_pct = base_sl
            tp_pct = base_tp
        
        # Confidence adjustment
        if confidence >= 0.90:
            tp_pct *= 1.2  # High conviction = let it run
        
        return {
            'stop_loss_price': entry_price * (1 - sl_pct),
            'stop_loss_pct': sl_pct,
            'take_profit_price': entry_price * (1 + tp_pct),
            'take_profit_pct': tp_pct,
            'trailing_activation': entry_price * (1 + tp_pct * 0.6),
            'trailing_pct': self.config.get('trailing_stop_pct', 0.005)
        }
    
    def record_trade_result(self, pnl: float):
        """Record trade result and update streak"""
        self.trades_today.append(pnl)
        
        if pnl >= 0:
            self.wins_today += 1
            if self.current_streak >= 0:
                self.current_streak += 1
            else:
                self.current_streak = 1
        else:
            self.losses_today += 1
            if self.current_streak <= 0:
                self.current_streak -= 1
            else:
                self.current_streak = -1
        
        # Re-adjust thresholds after each trade
        self._adjust_confidence_threshold()
    
    def get_opportunity_score(self, ticker: str, signal: Dict, price_data: Dict = None) -> float:
        """
        Score an opportunity 0-100
        Higher = better opportunity
        """
        score = 50  # Start neutral
        
        confidence = signal.get('confidence', 0)
        strategy = signal.get('strategy', '')
        
        # Confidence contribution (0-25 points)
        score += (confidence - 0.7) * 100  # 0.7 = 0pts, 0.9 = 20pts
        
        # Strategy alignment with pulse (0-20 points)
        if self.current_pulse in ['STRONG_UP', 'UP']:
            if strategy in ['momentum', 'trend_following', 'breakout']:
                score += 20
            elif strategy == 'mean_reversion':
                score -= 10
        elif self.current_pulse in ['STRONG_DOWN', 'DOWN']:
            if strategy == 'mean_reversion':
                score += 15
            elif strategy in ['momentum', 'breakout']:
                score -= 15
        
        # Time of day (0-10 points)
        et = get_eastern_time()
        if self.morning_session[0] <= et.time() <= dtime(10, 30):
            score += 10  # Best time
        elif et.time() >= dtime(15, 0):
            score -= 10  # Risky time
        
        # Streak adjustment (±5 points)
        if self.current_streak >= 2:
            score += 5
        elif self.current_streak <= -2:
            score -= 5
        
        return max(0, min(100, score))
    
    def get_status(self) -> Dict:
        """Get current adaptive intelligence status"""
        return {
            'pulse': self.current_pulse,
            'confidence_threshold': self.current_confidence_threshold,
            'day_change_pct': ((self.last_spy_price - self.day_start_spy) / self.day_start_spy * 100) if self.day_start_spy and self.last_spy_price else 0,
            'trades_today': len(self.trades_today),
            'wins': self.wins_today,
            'losses': self.losses_today,
            'streak': self.current_streak,
            'win_rate': (self.wins_today / len(self.trades_today) * 100) if self.trades_today else 0
        }
    
    def get_session_phase(self) -> str:
        """Get current trading session phase"""
        et = get_eastern_time()
        current_time = et.time()
        
        if current_time < dtime(9, 30):
            return 'PRE_MARKET'
        elif current_time <= dtime(10, 0):
            return 'OPENING'
        elif current_time <= self.morning_session[1]:
            return 'MORNING'
        elif current_time <= self.midday_session[1]:
            return 'MIDDAY'
        elif current_time <= self.afternoon_session[1]:
            return 'AFTERNOON'
        elif current_time <= dtime(16, 0):
            return 'CLOSING'
        else:
            return 'AFTER_HOURS'
