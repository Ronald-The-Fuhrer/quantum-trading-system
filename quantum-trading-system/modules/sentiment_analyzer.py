"""
ENHANCED SENTIMENT ANALYZER v2.0 - ACTIVE NEWS FILTERING
═══════════════════════════════════════════════════════════════════════════════

ACTIVELY USED IN TRADE DECISIONS:
1. Fetches news for stocks before entry
2. Analyzes sentiment (positive/negative/neutral)
3. Detects danger keywords (lawsuit, investigation, bankruptcy)
4. Boosts confidence on positive catalysts
5. Blocks trades on severely negative news

═══════════════════════════════════════════════════════════════════════════════
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class EnhancedSentimentAnalyzer:
    """Active news sentiment analysis for trade filtering"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.newsapi_key = config.get('newsapi_key', '')
        
        # Cache to avoid repeated API calls
        self._cache = {}
        self._cache_duration = timedelta(minutes=15)
        
        # API rate limiting (NewsAPI free = 100/day)
        self._api_calls_today = 0
        self._max_daily_calls = 100
        self._last_api_reset = datetime.now().date()
        
        # Sentiment keywords
        self.positive_keywords = [
            'upgrade', 'buy rating', 'beat expectations', 'record revenue',
            'fda approval', 'partnership', 'acquisition', 'dividend increase',
            'stock buyback', 'strong earnings', 'outperform', 'bullish',
            'growth', 'expansion', 'breakthrough', 'contract win', 
            'raised guidance', 'beat estimates', 'all-time high', 'deal'
        ]
        
        self.negative_keywords = [
            'lawsuit', 'investigation', 'sec probe', 'fraud', 'bankruptcy',
            'downgrade', 'sell rating', 'miss expectations', 'warning',
            'layoffs', 'restructuring', 'debt', 'default', 'recall',
            'scandal', 'resign', 'criminal', 'data breach', 'fine',
            'profit warning', 'guidance cut', 'disappointing', 'plunge'
        ]
        
        self.danger_keywords = [
            'bankruptcy', 'fraud', 'sec investigation', 'criminal charges',
            'accounting irregularities', 'delisting', 'default', 'insolvent'
        ]
        
        # Company mappings for better search
        self.ticker_to_company = {
            'AAPL': 'Apple', 'MSFT': 'Microsoft', 'GOOGL': 'Google',
            'AMZN': 'Amazon', 'META': 'Meta Facebook', 'NVDA': 'Nvidia',
            'TSLA': 'Tesla', 'AMD': 'AMD', 'JPM': 'JPMorgan', 'V': 'Visa',
            'JNJ': 'Johnson Johnson', 'UNH': 'UnitedHealth', 'HD': 'Home Depot',
            'BAC': 'Bank of America', 'XOM': 'Exxon', 'PFE': 'Pfizer',
            'NFLX': 'Netflix', 'DIS': 'Disney', 'WMT': 'Walmart', 'COST': 'Costco',
            'MA': 'Mastercard', 'PG': 'Procter Gamble', 'KO': 'Coca-Cola',
            'PEP': 'PepsiCo', 'MRK': 'Merck', 'ABBV': 'AbbVie', 'CRM': 'Salesforce',
            'ADBE': 'Adobe', 'ORCL': 'Oracle', 'CSCO': 'Cisco', 'INTC': 'Intel',
            'IBM': 'IBM', 'QCOM': 'Qualcomm', 'TXN': 'Texas Instruments',
            'AVGO': 'Broadcom', 'ACN': 'Accenture'
        }
        
        logger.info(f"SentimentAnalyzer v2.0 | API: {'Ready' if self.newsapi_key else 'Missing'}")
    
    def analyze_ticker(self, ticker: str) -> Dict:
        """Analyze news sentiment for a ticker"""
        # Check cache
        cache_key = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H')}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Default neutral result
        result = {
            'sentiment': 'NEUTRAL',
            'score': 0.0,
            'confidence_adjustment': 0.0,
            'should_trade': True,
            'reason': 'No recent news',
            'headlines': [],
            'positive_count': 0,
            'negative_count': 0
        }
        
        # Check API limit
        if not self._check_api_limit():
            result['reason'] = 'API limit reached'
            return result
        
        # Fetch and analyze news
        headlines = self._fetch_news(ticker)
        if headlines:
            result = self._analyze_headlines(ticker, headlines)
        
        self._cache[cache_key] = result
        return result
    
    def _check_api_limit(self) -> bool:
        """Check API call limit"""
        today = datetime.now().date()
        if today > self._last_api_reset:
            self._api_calls_today = 0
            self._last_api_reset = today
        return self._api_calls_today < self._max_daily_calls
    
    def _fetch_news(self, ticker: str) -> List[str]:
        """Fetch news from NewsAPI"""
        if not self.newsapi_key:
            return []
        
        try:
            company = self.ticker_to_company.get(ticker, ticker)
            query = f'"{company}" OR "{ticker}" stock'
            
            url = 'https://newsapi.org/v2/everything'
            params = {
                'q': query,
                'apiKey': self.newsapi_key,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 10,
                'from': (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            }
            
            response = requests.get(url, params=params, timeout=10)
            self._api_calls_today += 1
            
            if response.status_code == 200:
                data = response.json()
                headlines = []
                for article in data.get('articles', []):
                    if article.get('title'):
                        headlines.append(article['title'].lower())
                    if article.get('description'):
                        headlines.append(article['description'].lower())
                return headlines
            else:
                logger.warning(f"NewsAPI error: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"News fetch error {ticker}: {e}")
            return []
    
    def _analyze_headlines(self, ticker: str, headlines: List[str]) -> Dict:
        """Analyze sentiment from headlines"""
        positive_count = 0
        negative_count = 0
        danger_detected = False
        danger_reason = None
        
        combined = ' '.join(headlines)
        
        # Check danger keywords first
        for kw in self.danger_keywords:
            if kw in combined:
                danger_detected = True
                danger_reason = f"DANGER: '{kw}' in news"
                break
        
        # Count sentiment keywords
        for kw in self.positive_keywords:
            positive_count += combined.count(kw)
        for kw in self.negative_keywords:
            negative_count += combined.count(kw)
        
        # Calculate score
        total = positive_count + negative_count
        score = (positive_count - negative_count) / total if total > 0 else 0.0
        
        # Determine outcome
        if danger_detected:
            return {
                'sentiment': 'DANGER',
                'score': -1.0,
                'confidence_adjustment': -0.20,
                'should_trade': False,
                'reason': danger_reason,
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
        elif negative_count >= 3 and negative_count > positive_count * 2:
            return {
                'sentiment': 'NEGATIVE',
                'score': score,
                'confidence_adjustment': -0.10,
                'should_trade': False,
                'reason': f"High negative sentiment ({negative_count} keywords)",
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
        elif negative_count > positive_count:
            return {
                'sentiment': 'NEGATIVE',
                'score': score,
                'confidence_adjustment': -0.05,
                'should_trade': True,
                'reason': f"Mildly negative ({negative_count}neg vs {positive_count}pos)",
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
        elif positive_count >= 3 and positive_count > negative_count * 2:
            return {
                'sentiment': 'POSITIVE',
                'score': score,
                'confidence_adjustment': +0.05,
                'should_trade': True,
                'reason': f"Positive catalysts ({positive_count} keywords)",
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
        elif positive_count > negative_count:
            return {
                'sentiment': 'POSITIVE',
                'score': score,
                'confidence_adjustment': +0.02,
                'should_trade': True,
                'reason': f"Mildly positive ({positive_count}pos vs {negative_count}neg)",
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
        else:
            return {
                'sentiment': 'NEUTRAL',
                'score': 0.0,
                'confidence_adjustment': 0.0,
                'should_trade': True,
                'reason': 'Neutral/mixed news',
                'headlines': headlines[:3],
                'positive_count': positive_count,
                'negative_count': negative_count
            }
    
    def should_enter_trade(self, ticker: str, base_confidence: float) -> Tuple[bool, float, str]:
        """
        Main entry point - check if trade should proceed
        
        Returns: (should_trade, adjusted_confidence, reason)
        """
        result = self.analyze_ticker(ticker)
        
        adjusted = base_confidence + result['confidence_adjustment']
        adjusted = max(0.0, min(1.0, adjusted))
        
        if not result['should_trade']:
            return False, adjusted, f"NEWS BLOCKED: {result['reason']}"
        
        return True, adjusted, f"News: {result['sentiment']} ({result['reason']})"
    
    def get_status(self) -> Dict:
        """Get analyzer status"""
        return {
            'api_key_set': bool(self.newsapi_key),
            'api_calls_today': self._api_calls_today,
            'api_calls_remaining': self._max_daily_calls - self._api_calls_today,
            'cache_size': len(self._cache)
        }


# Backward compatibility
SentimentAnalyzer = EnhancedSentimentAnalyzer
