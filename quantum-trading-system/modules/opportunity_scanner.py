"""
OPPORTUNITY SCANNER v1.0
═══════════════════════════════════════════════════════════════════════════════

Scans the market for the BEST opportunities, not just any opportunity.

PHILOSOPHY:
- Quality over quantity
- Align with market direction
- Find stocks moving WITH momentum
- Avoid stocks fighting the trend

SCANNING METHODS:
1. MOMENTUM LEADERS - Stocks leading the market move
2. BREAKOUT CANDIDATES - Breaking key levels with volume
3. MEAN REVERSION SETUPS - Oversold bounces in uptrend
4. SECTOR ROTATION - Find hot sectors
5. RELATIVE STRENGTH - Outperformers vs SPY

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5))


class OpportunityScanner:
    """Finds the best trading opportunities"""
    
    def __init__(self, config: Dict, data_manager=None):
        self.config = config
        self.data_manager = data_manager
        
        # Sector definitions
        self.sectors = {
            'TECH': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'INTC', 'CRM', 'ADBE', 'ORCL'],
            'FINANCE': ['JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'AXP', 'V', 'MA'],
            'HEALTH': ['JNJ', 'UNH', 'PFE', 'MRK', 'ABBV', 'LLY', 'TMO', 'ABT', 'BMY', 'AMGN'],
            'CONSUMER': ['AMZN', 'TSLA', 'HD', 'NKE', 'MCD', 'SBUX', 'TGT', 'COST', 'WMT', 'PG'],
            'ENERGY': ['XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'MPC', 'PSX', 'VLO', 'OXY'],
            'INDUSTRIAL': ['CAT', 'DE', 'BA', 'HON', 'UPS', 'UNP', 'RTX', 'LMT', 'GE', 'MMM']
        }
        
        # Quick-trade candidates (high volume, liquid)
        self.liquid_stocks = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD',
            'JPM', 'BAC', 'XOM', 'JNJ', 'V', 'PG', 'HD', 'MA', 'UNH', 'DIS',
            'NFLX', 'PYPL', 'INTC', 'CSCO', 'PFE', 'KO', 'PEP', 'MRK', 'ABT',
            'CRM', 'ORCL', 'ADBE', 'NOW', 'QCOM', 'TXN', 'AVGO', 'COST', 'WMT'
        ]
        
        # Cache for scanned data
        self._cache = {}
        self._cache_time = None
        self._cache_duration = timedelta(minutes=5)
        
        logger.info(f"OpportunityScanner initialized with {len(self.liquid_stocks)} liquid stocks")
    
    def scan_momentum_leaders(self, market_direction: str) -> List[Dict]:
        """Find stocks leading the market move"""
        leaders = []
        
        if not self.data_manager:
            return leaders
        
        for ticker in self.liquid_stocks[:20]:  # Top 20 most liquid
            try:
                data = self.data_manager.get_quote(ticker)
                if not data:
                    continue
                
                change_pct = data.get('change_pct', 0)
                
                # In up market, find stocks up more than market
                if market_direction in ['STRONG_UP', 'UP']:
                    if change_pct > 0.5:  # Up more than 0.5%
                        leaders.append({
                            'ticker': ticker,
                            'change_pct': change_pct,
                            'type': 'MOMENTUM_LEADER',
                            'strength': change_pct / 0.5  # Relative strength
                        })
                # In down market, find stocks holding up
                elif market_direction in ['STRONG_DOWN', 'DOWN']:
                    if change_pct > -0.2:  # Not down much
                        leaders.append({
                            'ticker': ticker,
                            'change_pct': change_pct,
                            'type': 'RELATIVE_STRENGTH',
                            'strength': (change_pct + 1) / 1  # Normalized
                        })
            except Exception as e:
                logger.debug(f"Error scanning {ticker}: {e}")
                continue
        
        # Sort by strength
        leaders.sort(key=lambda x: x.get('strength', 0), reverse=True)
        return leaders[:5]  # Top 5
    
    def scan_oversold_bounces(self) -> List[Dict]:
        """Find oversold stocks starting to bounce"""
        bounces = []
        
        if not self.data_manager:
            return bounces
        
        for ticker in self.liquid_stocks[:30]:
            try:
                # Get historical data for RSI-like calculation
                df = self.data_manager.fetch_historical_data(ticker, period='5d', interval='15m')
                if df is None or len(df) < 20:
                    continue
                
                # Simple oversold detection
                prices = df['Close'].values
                recent_low = min(prices[-10:])
                current = prices[-1]
                avg_20 = sum(prices[-20:]) / 20
                
                # Bouncing from recent low
                if current > recent_low * 1.005 and current < avg_20 * 0.99:
                    bounces.append({
                        'ticker': ticker,
                        'bounce_pct': (current - recent_low) / recent_low * 100,
                        'below_avg_pct': (avg_20 - current) / avg_20 * 100,
                        'type': 'OVERSOLD_BOUNCE'
                    })
            except Exception as e:
                logger.debug(f"Error scanning bounce {ticker}: {e}")
                continue
        
        bounces.sort(key=lambda x: x.get('bounce_pct', 0), reverse=True)
        return bounces[:3]
    
    def get_hot_sector(self) -> Tuple[str, float]:
        """Identify the hottest sector today"""
        sector_performance = {}
        
        if not self.data_manager:
            return 'UNKNOWN', 0
        
        for sector, tickers in self.sectors.items():
            changes = []
            for ticker in tickers[:5]:  # Sample 5 from each
                try:
                    data = self.data_manager.get_quote(ticker)
                    if data:
                        changes.append(data.get('change_pct', 0))
                except:
                    continue
            
            if changes:
                sector_performance[sector] = sum(changes) / len(changes)
        
        if sector_performance:
            hot_sector = max(sector_performance, key=sector_performance.get)
            return hot_sector, sector_performance[hot_sector]
        
        return 'UNKNOWN', 0
    
    def get_best_opportunities(self, market_pulse: str, limit: int = 5) -> List[Dict]:
        """
        Get the best opportunities based on current market conditions
        """
        opportunities = []
        
        # Get momentum leaders
        leaders = self.scan_momentum_leaders(market_pulse)
        for l in leaders:
            l['score'] = 70 + l.get('strength', 0) * 10
            opportunities.append(l)
        
        # In neutral/down markets, also check bounces
        if market_pulse in ['NEUTRAL', 'DOWN']:
            bounces = self.scan_oversold_bounces()
            for b in bounces:
                b['score'] = 60 + b.get('bounce_pct', 0) * 5
                opportunities.append(b)
        
        # Get hot sector stocks
        hot_sector, sector_perf = self.get_hot_sector()
        if sector_perf > 0.3 and hot_sector in self.sectors:
            for ticker in self.sectors[hot_sector][:3]:
                opportunities.append({
                    'ticker': ticker,
                    'type': 'HOT_SECTOR',
                    'sector': hot_sector,
                    'score': 65 + sector_perf * 10
                })
        
        # Deduplicate and sort
        seen = set()
        unique = []
        for opp in opportunities:
            ticker = opp.get('ticker')
            if ticker not in seen:
                seen.add(ticker)
                unique.append(opp)
        
        unique.sort(key=lambda x: x.get('score', 0), reverse=True)
        return unique[:limit]
    
    def prioritize_signals(self, signals: List[Dict], market_pulse: str) -> List[Dict]:
        """
        Reorder signals by opportunity quality
        """
        if not signals:
            return signals
        
        # Get current opportunities
        opportunities = self.get_best_opportunities(market_pulse)
        opportunity_tickers = {o['ticker'] for o in opportunities}
        
        # Score each signal
        scored = []
        for sig in signals:
            ticker = sig.get('ticker', '')
            score = sig.get('confidence', 0) * 50  # Base score from confidence
            
            # Boost if in opportunities list
            if ticker in opportunity_tickers:
                score += 30
            
            # Boost liquid stocks
            if ticker in self.liquid_stocks:
                score += 10
            
            sig['priority_score'] = score
            scored.append(sig)
        
        scored.sort(key=lambda x: x.get('priority_score', 0), reverse=True)
        return scored
