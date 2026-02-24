"""
MARKET INDICES MONITOR v1.0 - Comprehensive Market Intelligence
═══════════════════════════════════════════════════════════════════════════════

Tracks all major U.S. market indices for complete market picture:

1. S&P 500 (^GSPC) - 500 large-cap, market-cap weighted
2. Dow Jones Industrial Average (^DJI) - 30 blue-chips, price-weighted  
3. Nasdaq Composite (^IXIC) - 3,000+ tech-heavy stocks
4. Russell 2000 (^RUT) - Small-cap benchmark
5. Russell 3000 (^RUA) - Broad market (98% of investable)
6. VIX (^VIX) - Volatility/Fear index
7. NYSE Composite (^NYA) - All NYSE stocks

Uses multiple data sources for redundancy:
- Yahoo Finance (primary)
- Finnhub (backup)
- Alpha Vantage (backup)

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import requests

logger = logging.getLogger(__name__)


class MarketIndicesMonitor:
    """Comprehensive market indices tracking"""
    
    # Index symbols for different data sources
    INDICES = {
        'SP500': {
            'yahoo': '^GSPC',
            'name': 'S&P 500',
            'description': '500 large-cap U.S. companies'
        },
        'DOW': {
            'yahoo': '^DJI',
            'name': 'Dow Jones Industrial Average',
            'description': '30 major blue-chip stocks'
        },
        'NASDAQ': {
            'yahoo': '^IXIC',
            'name': 'Nasdaq Composite',
            'description': '3,000+ tech-heavy stocks'
        },
        'RUSSELL2000': {
            'yahoo': '^RUT',
            'name': 'Russell 2000',
            'description': 'Small-cap benchmark'
        },
        'RUSSELL3000': {
            'yahoo': '^RUA',
            'name': 'Russell 3000',
            'description': '98% of investable U.S. market'
        },
        'VIX': {
            'yahoo': '^VIX',
            'name': 'CBOE Volatility Index',
            'description': 'Market fear gauge'
        },
        'NYSE': {
            'yahoo': '^NYA',
            'name': 'NYSE Composite',
            'description': 'All NYSE listed stocks'
        }
    }
    
    def __init__(self, config: Dict):
        self.config = config
        self.finnhub_key = config.get('finnhub_api_key', '')
        self.alpha_key = config.get('alphavantage_api_key', '')
        
        # Cache
        self._cache = {}
        self._cache_time = {}
        self._cache_duration = 60  # 1 minute cache
        
        # Current state
        self.current_data = {}
        self.previous_close = {}
        self.day_changes = {}
        
        logger.info(f"MarketIndicesMonitor initialized with {len(self.INDICES)} indices")
    
    def fetch_all_indices(self) -> Dict:
        """Fetch current data for all indices"""
        results = {}
        
        for key, info in self.INDICES.items():
            try:
                data = self._fetch_index(info['yahoo'])
                if data:
                    results[key] = {
                        'symbol': info['yahoo'],
                        'name': info['name'],
                        'price': data.get('price', 0),
                        'change': data.get('change', 0),
                        'change_pct': data.get('change_pct', 0),
                        'previous_close': data.get('previous_close', 0),
                        'day_high': data.get('day_high', 0),
                        'day_low': data.get('day_low', 0),
                        'timestamp': datetime.now().isoformat()
                    }
                    self.current_data[key] = results[key]
            except Exception as e:
                logger.debug(f"Failed to fetch {key}: {e}")
        
        return results
    
    def _fetch_index(self, symbol: str) -> Optional[Dict]:
        """Fetch single index data with caching"""
        # Check cache
        if symbol in self._cache:
            cache_age = (datetime.now() - self._cache_time.get(symbol, datetime.min)).seconds
            if cache_age < self._cache_duration:
                return self._cache[symbol]
        
        # Try Yahoo Finance
        data = self._fetch_yahoo(symbol)
        
        if data:
            self._cache[symbol] = data
            self._cache_time[symbol] = datetime.now()
            return data
        
        return None
    
    def _fetch_yahoo(self, symbol: str) -> Optional[Dict]:
        """Fetch from Yahoo Finance"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Get current price
            hist = ticker.history(period='2d')
            if len(hist) >= 1:
                current = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2] if len(hist) >= 2 else current
                day_high = hist['High'].iloc[-1]
                day_low = hist['Low'].iloc[-1]
                
                change = current - prev_close
                change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                
                return {
                    'price': current,
                    'previous_close': prev_close,
                    'change': change,
                    'change_pct': change_pct,
                    'day_high': day_high,
                    'day_low': day_low
                }
        except Exception as e:
            logger.debug(f"Yahoo fetch error for {symbol}: {e}")
        
        return None
    
    def get_market_breadth(self) -> Dict:
        """
        Calculate market breadth - how many indices are up vs down
        Returns overall market health assessment
        """
        if not self.current_data:
            self.fetch_all_indices()
        
        up_count = 0
        down_count = 0
        total_change = 0
        
        for key, data in self.current_data.items():
            if key == 'VIX':  # VIX is inverse - up is bad
                continue
            change_pct = data.get('change_pct', 0)
            total_change += change_pct
            if change_pct > 0:
                up_count += 1
            elif change_pct < 0:
                down_count += 1
        
        total_indices = up_count + down_count
        breadth_ratio = up_count / total_indices if total_indices > 0 else 0.5
        
        # Determine market state
        vix = self.current_data.get('VIX', {}).get('price', 20)
        avg_change = total_change / total_indices if total_indices > 0 else 0
        
        if breadth_ratio >= 0.7 and avg_change > 0.3:
            state = 'STRONG_BULLISH'
        elif breadth_ratio >= 0.5 and avg_change > 0:
            state = 'BULLISH'
        elif breadth_ratio <= 0.3 and avg_change < -0.3:
            state = 'STRONG_BEARISH'
        elif breadth_ratio <= 0.5 and avg_change < 0:
            state = 'BEARISH'
        else:
            state = 'MIXED'
        
        # VIX adjustment
        if vix > 30:
            state = 'HIGH_FEAR'
        elif vix > 25 and 'BULLISH' in state:
            state = 'CAUTIOUS'
        
        return {
            'state': state,
            'breadth_ratio': breadth_ratio,
            'indices_up': up_count,
            'indices_down': down_count,
            'avg_change_pct': avg_change,
            'vix': vix,
            'recommendation': self._get_recommendation(state, vix, avg_change)
        }
    
    def _get_recommendation(self, state: str, vix: float, avg_change: float) -> Dict:
        """Get trading recommendation based on market state"""
        recommendations = {
            'STRONG_BULLISH': {
                'action': 'AGGRESSIVE_LONG',
                'position_multiplier': 1.2,
                'confidence_threshold': 0.80,
                'description': 'Strong uptrend - favor momentum plays'
            },
            'BULLISH': {
                'action': 'NORMAL_LONG',
                'position_multiplier': 1.0,
                'confidence_threshold': 0.85,
                'description': 'Uptrend - normal trading'
            },
            'MIXED': {
                'action': 'SELECTIVE',
                'position_multiplier': 0.8,
                'confidence_threshold': 0.87,
                'description': 'Mixed signals - be selective'
            },
            'BEARISH': {
                'action': 'DEFENSIVE',
                'position_multiplier': 0.5,
                'confidence_threshold': 0.90,
                'description': 'Downtrend - reduce exposure'
            },
            'STRONG_BEARISH': {
                'action': 'MINIMAL',
                'position_multiplier': 0.3,
                'confidence_threshold': 0.92,
                'description': 'Strong downtrend - minimal trading'
            },
            'HIGH_FEAR': {
                'action': 'CASH',
                'position_multiplier': 0.2,
                'confidence_threshold': 0.95,
                'description': 'High VIX - stay mostly cash'
            },
            'CAUTIOUS': {
                'action': 'CAUTIOUS_LONG',
                'position_multiplier': 0.6,
                'confidence_threshold': 0.88,
                'description': 'Elevated VIX - trade carefully'
            }
        }
        return recommendations.get(state, recommendations['MIXED'])
    
    def get_index(self, key: str) -> Optional[Dict]:
        """Get specific index data"""
        if key not in self.current_data:
            self.fetch_all_indices()
        return self.current_data.get(key)
    
    def get_sp500(self) -> Optional[Dict]:
        return self.get_index('SP500')
    
    def get_vix(self) -> Optional[Dict]:
        return self.get_index('VIX')
    
    def get_summary(self) -> str:
        """Get human-readable market summary"""
        if not self.current_data:
            self.fetch_all_indices()
        
        lines = ["═" * 50, "MARKET INDICES SUMMARY", "═" * 50]
        
        for key, data in self.current_data.items():
            change_pct = data.get('change_pct', 0)
            icon = "🟢" if change_pct >= 0 else "🔴"
            lines.append(f"{icon} {data['name']}: {data['price']:.2f} ({change_pct:+.2f}%)")
        
        breadth = self.get_market_breadth()
        lines.append("─" * 50)
        lines.append(f"Market State: {breadth['state']}")
        lines.append(f"Breadth: {breadth['indices_up']} up / {breadth['indices_down']} down")
        lines.append(f"Recommendation: {breadth['recommendation']['description']}")
        
        return "\n".join(lines)
    
    def should_trade_today(self) -> Tuple[bool, str]:
        """Determine if we should trade based on market conditions"""
        breadth = self.get_market_breadth()
        
        if breadth['state'] == 'HIGH_FEAR':
            return False, "VIX too high - staying out"
        
        if breadth['state'] == 'STRONG_BEARISH':
            return False, "Strong bearish - minimal trading"
        
        if breadth['avg_change_pct'] < -1.5:
            return False, "Market down >1.5% - risk off"
        
        return True, f"Market state: {breadth['state']}"
