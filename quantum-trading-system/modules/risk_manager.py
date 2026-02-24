"""
Risk Manager - Kelly Criterion, VaR, CVaR, Drawdown Protection
FIXED VERSION - Works with live broker data
"""
import numpy as np
from scipy import stats
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class QuantumRiskManager:
    """Advanced risk management with multiple methodologies"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.max_position_size = config.get('max_position_size', 0.05)
        self.max_portfolio_risk = config.get('max_portfolio_risk', 0.02)
        self.max_drawdown = config.get('max_drawdown', 0.15)
        self.max_leverage = config.get('max_leverage', 1.0)
        self.max_correlation = config.get('max_correlation', 0.7)
        self.var_confidence = config.get('var_confidence', 0.95)
        
        # These will be set from portfolio_manager's live data
        self.peak_value = 0
        self.initial_capital = 0
        self.daily_pnl = []
        self.trade_history = []
        self.position_history = {}
    
    def set_initial_capital(self, capital: float):
        """Set initial capital from live broker data"""
        self.initial_capital = capital
        if self.peak_value == 0:
            self.peak_value = capital
        logger.info(f"Risk manager initialized with capital: ${capital:,.2f}")
    
    def update_peak(self, current_value: float):
        """Update peak value if current is higher"""
        if current_value > self.peak_value:
            self.peak_value = current_value
    
    def kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float,
                       fraction: float = 0.25) -> float:
        """Kelly Criterion for position sizing"""
        if avg_loss == 0 or win_rate >= 1 or win_rate <= 0:
            return 0.01
        
        win_loss_ratio = avg_win / abs(avg_loss)
        kelly = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        
        # Fractional Kelly for safety
        return max(0.01, min(kelly * fraction, self.max_position_size))
    
    def calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Value at Risk"""
        if len(returns) < 30:
            return 0.02
        return abs(np.percentile(returns, (1 - confidence) * 100))
    
    def calculate_cvar(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional Value at Risk (Expected Shortfall)"""
        var = self.calculate_var(returns, confidence)
        return abs(returns[returns <= -var].mean()) if any(returns <= -var) else var
    
    def calculate_sharpe_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
        """Sharpe Ratio"""
        if len(returns) < 2:
            return 0.0
        excess_returns = returns - risk_free_rate / 252
        return np.mean(excess_returns) / (np.std(excess_returns) + 1e-10) * np.sqrt(252)
    
    def calculate_sortino_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
        """Sortino Ratio (downside deviation only)"""
        if len(returns) < 2:
            return 0.0
        excess_returns = returns - risk_free_rate / 252
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 0 else np.std(returns)
        return np.mean(excess_returns) / (downside_std + 1e-10) * np.sqrt(252)
    
    def calculate_calmar_ratio(self, returns: np.ndarray, equity_curve: np.ndarray) -> float:
        """Calmar Ratio (return / max drawdown)"""
        annual_return = np.mean(returns) * 252
        max_dd = self.calculate_max_drawdown(equity_curve)
        return annual_return / (max_dd + 1e-10)
    
    def calculate_max_drawdown(self, equity_curve: np.ndarray) -> float:
        """Maximum Drawdown"""
        if len(equity_curve) < 2:
            return 0.0
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - running_max) / running_max
        return abs(drawdown.min())
    
    def position_sizing_volatility_adjusted(self, volatility: float, 
                                           target_volatility: float = 0.15) -> float:
        """Volatility-adjusted position sizing"""
        if volatility <= 0:
            return self.max_position_size
        size = target_volatility / volatility * self.max_position_size
        return max(0.01, min(size, self.max_position_size))
    
    def calculate_position_size(self, ticker: str, signal_strength: float,
                               volatility: float, portfolio_value: float,
                               win_rate: float = 0.55, avg_win: float = 0.02,
                               avg_loss: float = 0.01) -> float:
        """Calculate optimal position size using multiple methods"""
        # Kelly Criterion
        kelly_size = self.kelly_criterion(win_rate, avg_win, avg_loss)
        
        # Volatility adjustment
        vol_adjusted_size = self.position_sizing_volatility_adjusted(volatility)
        
        # Signal strength adjustment
        confidence_size = signal_strength * self.max_position_size
        
        # Take minimum for conservatism
        final_size = min(kelly_size, vol_adjusted_size, confidence_size)
        
        return portfolio_value * final_size
    
    def check_drawdown(self, current_value: float) -> Tuple[bool, float]:
        """
        Check if maximum drawdown exceeded.
        Uses peak value tracking for accurate drawdown calculation.
        """
        # Update peak if current value is higher
        if current_value > self.peak_value:
            self.peak_value = current_value
        
        # Calculate drawdown from peak
        if self.peak_value > 0:
            current_drawdown = (self.peak_value - current_value) / self.peak_value
        else:
            current_drawdown = 0.0
        
        # Check against limit
        if current_drawdown > self.max_drawdown:
            logger.error(f"⚠️  Maximum drawdown exceeded: {current_drawdown:.2%}")
            return False, current_drawdown
        
        # Log warning if approaching limit
        if current_drawdown > self.max_drawdown * 0.8:
            logger.warning(f"⚠️  Drawdown warning: {current_drawdown:.2%} (limit: {self.max_drawdown:.2%})")
        
        return True, current_drawdown
    
    def check_drawdown_from_initial(self, current_value: float, initial_capital: float) -> Tuple[bool, float]:
        """
        Alternative drawdown check from initial capital.
        Useful when peak tracking hasn't been established.
        """
        if initial_capital <= 0:
            return True, 0.0
        
        # Update peak
        if current_value > self.peak_value:
            self.peak_value = current_value
        
        # Use the higher of initial capital or peak for drawdown calculation
        reference_value = max(initial_capital, self.peak_value)
        
        if current_value >= reference_value:
            return True, 0.0
        
        current_drawdown = (reference_value - current_value) / reference_value
        
        if current_drawdown > self.max_drawdown:
            logger.error(f"⚠️  Maximum drawdown exceeded: {current_drawdown:.2%}")
            return False, current_drawdown
        
        return True, current_drawdown
    
    def should_reduce_exposure(self, recent_losses: int = 5) -> bool:
        """Check if should reduce exposure due to consecutive losses"""
        if len(self.trade_history) < recent_losses:
            return False
        
        recent_trades = list(self.trade_history)[-recent_losses:]
        consecutive_losses = sum(1 for trade in recent_trades if isinstance(trade, dict) and trade.get('pnl', 0) < 0)
        
        return consecutive_losses >= recent_losses * 0.6
    
    def add_trade(self, trade_data: Dict):
        """Add a trade to history for tracking"""
        self.trade_history.append(trade_data)
        # Keep only last 100 trades
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]
    
    def get_risk_summary(self, current_value: float) -> Dict:
        """Get current risk metrics summary"""
        _, drawdown = self.check_drawdown(current_value)
        
        return {
            'current_value': current_value,
            'peak_value': self.peak_value,
            'initial_capital': self.initial_capital,
            'drawdown': drawdown,
            'drawdown_pct': f"{drawdown:.2%}",
            'max_drawdown_limit': self.max_drawdown,
            'max_position_size': self.max_position_size,
            'trades_tracked': len(self.trade_history),
            'within_limits': drawdown <= self.max_drawdown
        }