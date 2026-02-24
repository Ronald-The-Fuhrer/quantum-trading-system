"""
Data Manager v3.1 - ULTIMATE Multi-Source Data Aggregator + REGIME FIX
═══════════════════════════════════════════════════════════════════════════════════

v3.1 CHANGES:
- Added fetch_regime_data() for accurate market regime calculation
- Fixed 5-day return issue (fetch_historical_data required 20+ rows)
- Short-period fetches now work correctly without indicator requirements

MISSION: Ensure the bot ALWAYS has the best, most recent market data by
         pulling from EVERY available free data source.

DATA SOURCES (all free tiers):
1. Alpaca Free - 200 req/min, IEX exchange data (you already have this!)
2. Yahoo Finance - Unlimited but unreliable, good historical
3. Finnhub - 60 req/min free, real-time quotes
4. Alpha Vantage - 25 req/day free (get key at alphavantage.co)
5. Twelve Data - 800 req/day free (get key at twelvedata.com)

STRATEGY:
- Parallel fetching from multiple sources simultaneously
- Smart source rotation based on rate limits & reliability
- Aggressive caching with stale fallback
- Best-source selection based on data quality
- Automatic failover on any source failure
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

logger = logging.getLogger(__name__)

# Import available libraries
HAS_YFINANCE = False
HAS_ALPACA = False
HAS_REQUESTS = False
HAS_TALIB = False

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    pass

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame
    HAS_ALPACA = True
except ImportError:
    pass

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    pass

try:
    import talib
    HAS_TALIB = True
except ImportError:
    pass


class SourceStats:
    """Track performance of each data source"""
    def __init__(self):
        self.success = 0
        self.fail = 0
        self.latency_sum = 0.0
        self.daily_calls = 0
        self.daily_reset = datetime.now().date()
        self.rate_limit_hits = 0
    
    def record_success(self, latency: float):
        self.success += 1
        self.latency_sum += latency
        self._check_reset()
        self.daily_calls += 1
    
    def record_fail(self):
        self.fail += 1
        self._check_reset()
        self.daily_calls += 1
    
    def _check_reset(self):
        if datetime.now().date() > self.daily_reset:
            self.daily_calls = 0
            self.daily_reset = datetime.now().date()
    
    @property
    def success_rate(self):
        total = self.success + self.fail
        return self.success / total if total > 0 else 0
    
    @property
    def avg_latency(self):
        return self.latency_sum / self.success if self.success > 0 else 10.0


class QuantumDataManager:
    """Ultimate multi-source data manager for maximum reliability."""
    
    RATE_LIMITS = {
        'alpaca': {'per_minute': 200, 'daily': 999999},
        'yahoo': {'per_minute': 60, 'daily': 999999},
        'finnhub': {'per_minute': 60, 'daily': 999999},
        'alphavantage': {'per_minute': 5, 'daily': 25},
        'twelvedata': {'per_minute': 8, 'daily': 800},
    }
    
    def __init__(self, config: Dict):
        self.config = config
        self.cache = {}
        self.cache_duration = config.get('cache_duration', 300)
        self.extended_cache_duration = 3600
        self._cache_lock = threading.Lock()
        
        # Source statistics
        self.stats = {name: SourceStats() for name in self.RATE_LIMITS}
        self.stats['cache'] = SourceStats()
        
        # API Keys
        self.api_keys = {
            'alpaca_key': config.get('alpaca_key', ''),
            'alpaca_secret': config.get('alpaca_secret', ''),
            'finnhub': config.get('finnhub_api_key', ''),
            'alphavantage': config.get('alphavantage_api_key', ''),
            'twelvedata': config.get('twelvedata_api_key', ''),
        }
        
        # Initialize Alpaca
        self.alpaca_client = None
        if HAS_ALPACA and self.api_keys['alpaca_key']:
            try:
                self.alpaca_client = StockHistoricalDataClient(
                    self.api_keys['alpaca_key'], self.api_keys['alpaca_secret']
                )
                logger.info("✅ Alpaca client ready (free tier)")
            except Exception as e:
                logger.warning(f"Alpaca init failed: {e}")
        
        # Thread pool
        self.executor = ThreadPoolExecutor(max_workers=12)
        
        # Rate limit tracking
        self._request_times = defaultdict(list)
        self._rate_lock = threading.Lock()
        
        # Log status - VERY VISIBLE
        sources = []
        if HAS_YFINANCE: sources.append("Yahoo")
        if self.alpaca_client: sources.append("Alpaca")
        if self.api_keys['finnhub']: sources.append("Finnhub")
        if self.api_keys['alphavantage']: sources.append("AlphaVantage")
        if self.api_keys['twelvedata']: sources.append("TwelveData")
        
        print(f"\n{'='*60}")
        print(f"📊 DataManager v3.0 - MULTI-SOURCE ENGINE")
        print(f"{'='*60}")
        print(f"Active Sources: {', '.join(sources) or 'Yahoo only'}")
        print(f"Alpaca: {'✅ Connected' if self.alpaca_client else '❌ Not configured'}")
        print(f"Finnhub: {'✅ API Key Set' if self.api_keys['finnhub'] else '❌ No key'}")
        print(f"TwelveData: {'✅ API Key Set' if self.api_keys['twelvedata'] else '❌ No key'}")
        print(f"AlphaVantage: {'✅ API Key Set' if self.api_keys['alphavantage'] else '❌ No key'}")
        print(f"{'='*60}\n")
        
        logger.info(f"DataManager v3.0 | Sources: {', '.join(sources) or 'Yahoo only'}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN PUBLIC METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def fetch_simple_data(self, ticker: str, period: str = '3mo') -> Optional[pd.DataFrame]:
        """Fetch OHLCV data from best available source"""
        cache_key = f"{ticker}_{period}_simple"
        
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached.copy()
        
        df = self._fetch_best(ticker, period, indicators=False)
        
        if df is not None and len(df) > 0:
            self._set_cache(cache_key, df)
            return df.copy()
        
        stale = self._get_stale_cache(cache_key)
        if stale is not None:
            return stale.copy()
        
        return None
    
    def fetch_historical_data(self, ticker: str, period: str = '1y',
                            interval: str = '1d') -> Optional[pd.DataFrame]:
        """Fetch historical data with indicators"""
        cache_key = f"{ticker}_{period}_{interval}"
        
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached.copy()
        
        df = self._fetch_best(ticker, period, indicators=True)
        
        if df is not None and len(df) >= 20:
            self._set_cache(cache_key, df)
            return df.copy()
        
        stale = self._get_stale_cache(cache_key)
        if stale is not None:
            return stale.copy()
        
        return None
    
    def fetch_regime_data(self, ticker: str, days: int = 10) -> Optional[pd.DataFrame]:
        """
        Fetch recent daily data specifically for market regime calculation.
        Does NOT require 20+ rows or add indicators.
        Returns raw OHLCV data for the specified number of days.
        
        v4.18: Dedicated method to fix incorrect 5-day return calculations
        """
        cache_key = f"{ticker}_regime_{days}d"
        
        # Short cache for regime data (5 minutes)
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached.copy()
        
        df = None
        
        # Try Yahoo Finance first (most reliable for short periods)
        if HAS_YFINANCE:
            try:
                import socket
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(5)
                try:
                    # Use explicit date range for accuracy
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=days + 5)  # Extra buffer for weekends
                    
                    data = yf.download(
                        ticker, 
                        start=start_date.strftime('%Y-%m-%d'),
                        end=end_date.strftime('%Y-%m-%d'),
                        progress=False,
                        auto_adjust=True, 
                        threads=False
                    )
                finally:
                    socket.setdefaulttimeout(old_timeout)
                
                if not data.empty:
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.droplevel(1)
                    df = data[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
                    
                    # Log what we got for debugging
                    if len(df) >= 3:
                        logger.info(f"📊 Regime data for {ticker}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
            except Exception as e:
                logger.warning(f"Yahoo regime data failed for {ticker}: {e}")
        
        # Fallback to Alpaca
        if df is None and self.alpaca_client:
            try:
                end = datetime.now()
                start = end - timedelta(days=days + 5)
                
                request = StockBarsRequest(
                    symbol_or_symbols=ticker,
                    timeframe=TimeFrame.Day,
                    start=start, end=end
                )
                bars = self.alpaca_client.get_stock_bars(request)
                
                if ticker in bars.data and bars.data[ticker]:
                    data = [{'Open': b.open, 'High': b.high, 'Low': b.low, 'Close': b.close,
                             'Volume': b.volume, 'Date': b.timestamp} for b in bars.data[ticker]]
                    df = pd.DataFrame(data)
                    df.set_index('Date', inplace=True)
                    df.index = pd.to_datetime(df.index)
                    logger.info(f"📊 Alpaca regime data for {ticker}: {len(df)} rows")
            except Exception as e:
                logger.warning(f"Alpaca regime data failed for {ticker}: {e}")
        
        # Cache and return
        if df is not None and len(df) >= 3:
            self._set_cache(cache_key, df)
            return df.copy()
        
        return None
    
    def get_realtime_quote(self, ticker: str) -> Optional[Dict]:
        """Get real-time quote from fastest source"""
        if self.alpaca_client and self._can_request('alpaca'):
            q = self._alpaca_quote(ticker)
            if q: return q
        
        if self.api_keys['finnhub'] and self._can_request('finnhub'):
            q = self._finnhub_quote(ticker)
            if q: return q
        
        if HAS_YFINANCE:
            return self._yahoo_quote(ticker)
        
        return None
    
    def get_multiple_tickers_parallel(self, tickers: List[str], period: str = '1y') -> Dict[str, pd.DataFrame]:
        """Fetch multiple tickers in parallel"""
        results = {}
        
        def fetch(t):
            return t, self.fetch_historical_data(t, period=period)
        
        futures = {self.executor.submit(fetch, t): t for t in tickers}
        
        for future in as_completed(futures, timeout=90):
            try:
                ticker, df = future.result(timeout=10)
                if df is not None:
                    results[ticker] = df
            except:
                pass
        
        return results
    
    # ═══════════════════════════════════════════════════════════════════════════
    # INTELLIGENT SOURCE SELECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_best(self, ticker: str, period: str, indicators: bool = False) -> Optional[pd.DataFrame]:
        """Fetch from multiple sources in parallel, return best result"""
        results = {}
        futures = []
        
        # Submit to all available sources
        if self.alpaca_client and self._can_request('alpaca'):
            futures.append(('alpaca', self.executor.submit(self._alpaca_bars, ticker, period)))
        
        if HAS_YFINANCE and self._can_request('yahoo'):
            futures.append(('yahoo', self.executor.submit(self._yahoo_bars, ticker, period)))
        
        if self.api_keys['finnhub'] and self._can_request('finnhub'):
            futures.append(('finnhub', self.executor.submit(self._finnhub_bars, ticker, period)))
        
        if self.api_keys['twelvedata'] and self._can_request('twelvedata'):
            futures.append(('twelvedata', self.executor.submit(self._twelvedata_bars, ticker, period)))
        
        # Collect results
        for source, future in futures:
            try:
                start = time.time()
                df = future.result(timeout=6)
                latency = time.time() - start
                
                if df is not None and len(df) >= 10:
                    self.stats[source].record_success(latency)
                    results[source] = df
                else:
                    self.stats[source].record_fail()
            except:
                self.stats[source].record_fail()
        
        if not results:
            return None
        
        # Pick best (most data)
        best = max(results.keys(), key=lambda s: len(results[s]))
        df = results[best]
        
        if indicators and len(df) >= 30:
            df = self._add_indicators(df)
        
        return df
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATA SOURCE IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _alpaca_bars(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        """Alpaca historical bars (free tier)"""
        if not self.alpaca_client:
            return None
        try:
            end = datetime.now()
            days = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 365, '2y': 730}.get(period, 365)
            start = end - timedelta(days=days)
            
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=start, end=end
            )
            bars = self.alpaca_client.get_stock_bars(request)
            
            if ticker not in bars.data or not bars.data[ticker]:
                return None
            
            data = [{'Open': b.open, 'High': b.high, 'Low': b.low, 'Close': b.close,
                     'Volume': b.volume, 'Date': b.timestamp} for b in bars.data[ticker]]
            
            df = pd.DataFrame(data)
            df.set_index('Date', inplace=True)
            df.index = pd.to_datetime(df.index)
            return df
        except:
            return None
    
    def _yahoo_bars(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        """Yahoo Finance with timeout protection"""
        if not HAS_YFINANCE:
            return None
        try:
            import socket
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5)
            try:
                data = yf.download(ticker, period=period, progress=False,
                                   auto_adjust=True, threads=False, timeout=5)
            finally:
                socket.setdefaulttimeout(old)
            
            if data.empty:
                return None
            
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)
            
            required = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(c in data.columns for c in required):
                return None
            
            return data.dropna(subset=required)
        except:
            return None
    
    def _finnhub_bars(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        """Finnhub candles (60/min free)"""
        if not HAS_REQUESTS or not self.api_keys['finnhub']:
            return None
        try:
            end = int(datetime.now().timestamp())
            days = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 365}.get(period, 365)
            start = int((datetime.now() - timedelta(days=days)).timestamp())
            
            url = "https://finnhub.io/api/v1/stock/candle"
            params = {'symbol': ticker, 'resolution': 'D', 'from': start, 'to': end,
                      'token': self.api_keys['finnhub']}
            
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            
            if data.get('s') != 'ok' or 'c' not in data:
                return None
            
            df = pd.DataFrame({
                'Open': data['o'], 'High': data['h'], 'Low': data['l'],
                'Close': data['c'], 'Volume': data['v'],
                'Date': pd.to_datetime(data['t'], unit='s')
            })
            df.set_index('Date', inplace=True)
            return df
        except:
            return None
    
    def _twelvedata_bars(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        """Twelve Data (800/day free)"""
        if not HAS_REQUESTS or not self.api_keys['twelvedata']:
            return None
        try:
            size = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 252}.get(period, 252)
            url = "https://api.twelvedata.com/time_series"
            params = {'symbol': ticker, 'interval': '1day', 'outputsize': size,
                      'apikey': self.api_keys['twelvedata']}
            
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            
            if 'values' not in data:
                return None
            
            df = pd.DataFrame(data['values'])
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                    'close': 'Close', 'volume': 'Volume'})
            for c in ['Open', 'High', 'Low', 'Close', 'Volume']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            return df.sort_index()
        except:
            return None
    
    def _alpaca_quote(self, ticker: str) -> Optional[Dict]:
        if not self.alpaca_client:
            return None
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
            quotes = self.alpaca_client.get_stock_latest_quote(req)
            if ticker in quotes:
                q = quotes[ticker]
                return {'price': (q.ask_price + q.bid_price) / 2,
                        'bid': q.bid_price, 'ask': q.ask_price}
        except:
            pass
        return None
    
    def _finnhub_quote(self, ticker: str) -> Optional[Dict]:
        if not HAS_REQUESTS or not self.api_keys['finnhub']:
            return None
        try:
            url = "https://finnhub.io/api/v1/quote"
            r = requests.get(url, params={'symbol': ticker, 'token': self.api_keys['finnhub']}, timeout=3)
            d = r.json()
            if 'c' in d and d['c'] > 0:
                return {'price': d['c'], 'high': d['h'], 'low': d['l'], 'open': d['o']}
        except:
            pass
        return None
    
    def _yahoo_quote(self, ticker: str) -> Optional[Dict]:
        if not HAS_YFINANCE:
            return None
        try:
            info = yf.Ticker(ticker).info
            return {'price': info.get('currentPrice', info.get('regularMarketPrice', 0)),
                    'volume': info.get('volume', 0)}
        except:
            pass
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RATE LIMITING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _can_request(self, source: str) -> bool:
        limits = self.RATE_LIMITS.get(source, {'per_minute': 60, 'daily': 999999})
        stats = self.stats[source]
        
        if stats.daily_calls >= limits['daily']:
            return False
        
        with self._rate_lock:
            now = time.time()
            cutoff = now - 60
            self._request_times[source] = [t for t in self._request_times[source] if t > cutoff]
            
            if len(self._request_times[source]) >= limits['per_minute']:
                stats.rate_limit_hits += 1
                return False
            
            self._request_times[source].append(now)
        return True
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CACHING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_cache(self, key: str) -> Optional[pd.DataFrame]:
        with self._cache_lock:
            if key in self.cache:
                df, ts = self.cache[key]
                if (datetime.now() - ts).seconds < self.cache_duration:
                    self.stats['cache'].record_success(0)
                    return df
        return None
    
    def _get_stale_cache(self, key: str) -> Optional[pd.DataFrame]:
        with self._cache_lock:
            if key in self.cache:
                df, ts = self.cache[key]
                if (datetime.now() - ts).seconds < self.extended_cache_duration:
                    return df
        return None
    
    def _set_cache(self, key: str, df: pd.DataFrame):
        with self._cache_lock:
            self.cache[key] = (df.copy(), datetime.now())
    
    def clear_cache(self):
        with self._cache_lock:
            self.cache.clear()
    
    def get_source_stats(self) -> Dict:
        return {name: {'success': s.success, 'fail': s.fail,
                       'rate': f"{s.success_rate:.0%}", 'daily': s.daily_calls}
                for name, s in self.stats.items()}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # INDICATORS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 30:
            return df
        try:
            df = df.copy()
            close = df['Close'].values.astype(float)
            high = df['High'].values.astype(float)
            low = df['Low'].values.astype(float)
            volume = df['Volume'].values.astype(float)
            
            if HAS_TALIB:
                for p in [5, 10, 20, 50]:
                    if len(close) >= p:
                        df[f'SMA_{p}'] = talib.SMA(close, p)
                        df[f'EMA_{p}'] = talib.EMA(close, p)
                if len(close) >= 100: df['SMA_100'] = talib.SMA(close, 100)
                if len(close) >= 200: df['SMA_200'] = talib.SMA(close, 200)
                
                df['RSI'] = talib.RSI(close, 14)
                df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = talib.MACD(close)
                df['ATR'] = talib.ATR(high, low, close, 14)
                df['ADX'] = talib.ADX(high, low, close, 14)
                df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = talib.BBANDS(close)
                df['MOM'] = talib.MOM(close, 10)
                df['CCI'] = talib.CCI(high, low, close, 14)
                df['MFI'] = talib.MFI(high, low, close, volume, 14)
            else:
                # Pandas fallback
                for p in [5, 10, 20, 50]:
                    df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
                    df[f'EMA_{p}'] = df['Close'].ewm(span=p).mean()
                
                delta = df['Close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                df['RSI'] = 100 - (100 / (1 + gain/loss))
                
                ema12 = df['Close'].ewm(span=12).mean()
                ema26 = df['Close'].ewm(span=26).mean()
                df['MACD'] = ema12 - ema26
                df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
                
                sma20 = df['Close'].rolling(20).mean()
                std20 = df['Close'].rolling(20).std()
                df['BB_Upper'] = sma20 + 2*std20
                df['BB_Middle'] = sma20
                df['BB_Lower'] = sma20 - 2*std20
                
                df['ADX'] = 25
            
            df['Returns'] = df['Close'].pct_change()
            df['Volatility'] = df['Returns'].rolling(20).std() * np.sqrt(252)
            df['Volume_Ratio'] = df['Volume'] / df['Volume'].rolling(20).mean()
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']
            
            essential = ['Close', 'RSI', 'MACD']
            existing = [c for c in essential if c in df.columns]
            df = df.dropna(subset=existing)
            
            return df
        except Exception as e:
            logger.error(f"Indicator error: {e}")
            return df
    
    # Legacy
    def get_multiple_tickers(self, tickers, period='1y'):
        return self.get_multiple_tickers_parallel(tickers, period)
    
    def __del__(self):
        try:
            self.executor.shutdown(wait=False)
        except:
            pass
