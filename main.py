"""
QUANTUM TRADING SYSTEM v10.3 - GHOST FIX + SPY FADE + ATR FILTER
═══════════════════════════════════════════════════════════════════════════════

v10.3 FIXES (Mar 13, 2026):
 1. CRITICAL: Ghost position bug — after EOD sell succeeded at Alpaca,
    internal position tracker still showed the ticker as open. This caused
    every subsequent cycle to re-attempt selling (qty=0 error), nuclear EOD
    to re-sell, and shutdown to re-sell again. Trade counter showed 4 trades
    (1 buy + 3 sells) instead of 2. Fix: Track sold tickers in 
    closed_eod_tickers set, skip all re-sell attempts for those tickers
    across EOD, nuclear, shutdown, and cycle exit signal processing.
 2. SPY fade filter — the old market check only tested if SPY was currently
    above -0.2%. This allowed entries when SPY was fading rapidly (e.g.
    +0.12% → +0.01% in 4 minutes). New filter tracks last 5 SPY readings
    and blocks entries if SPY dropped 0.3%+ from its recent cycle high.
 3. Exit evaluation entry price $0.00 bug — log_exit_evaluation was not
    passing entry_price or current_price to the reporter, causing the 
    session report to show $0.00 for both fields.

v10.1 FIXES (Mar 2-3, 2026):
 1. Position size 20% → 33% (unlocks stocks up to ~$165 on $500 account)
 2. Smart single-share buy (if target=0 but can afford 1, buy 1)
 3. ATR% filter in swing_strategy (reject low-volatility stocks like T)
 4. ALPACA PDT SYNC: Query broker's ACTUAL rolling 5-day daytrade_count
    before any BUY. Never buy if we can't sell same day.
 5. PDT-blocked graceful handling: If sell fails due to PDT, stop retrying,
    mark ticker for overnight hold, skip all further exit attempts today.
 6. Nuclear EOD now distinguishes PDT holds from real failures.

v10.0 CRITICAL FIXES (Feb 27, 2026):
1. FIXED: Windows sleep killed bot for 3h51m, missing 3:45 PM EOD liquidation!
   Added SetThreadExecutionState to prevent OS sleep during market hours.
2. FIXED: Bot ran until 5:17 PM after waking from sleep (past 4:00 PM close).
   Added HARD KILL at 4:05 PM + sleep gap detection (>5min gap = force EOD).
3. FIXED: T was double-sold (EOD + Nuclear) because position cache was stale.
   Nuclear now re-queries ACTUAL broker positions before selling.
4. FIXED: PDT state JSON serialization error (date not serializable).
5. ADDED: Cycle-based profit lock in swing_strategy v4.0 (see that file).

Retained from v9.9:
- EOD liquidation at 3:45 PM, nuclear at 3:55 PM
- 3 entry cap, 1:00 PM cutoff
- Stop losses force-execute (bypass PDT)

═══════════════════════════════════════════════════════════════════════════════
"""
import sys
import os
import warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'modules'))

from datetime import datetime, time as dtime, timedelta, timezone
import logging
import signal
import argparse
import time
import requests
from typing import Dict, List, Optional
import ctypes

# Core modules
from modules.config_manager import ConfigManager
from modules.database import QuantumDatabase
from modules.risk_manager import QuantumRiskManager
from modules.data_manager import QuantumDataManager
from modules.ml_engine import MLEngine
from modules.execution_engine import ExecutionEngine
from modules.portfolio_manager import PortfolioManager
from modules.logger import setup_logger

# PDT modules
from modules.pdt_tracker import PDTTracker
from modules.swing_strategy import SwingStrategyEngine
from modules.session_reporter import UltraVerboseReporter, init_reporter

# Protection modules
try:
    from modules.regime_detector import RegimeDetector
    HAS_REGIME = True
except ImportError:
    HAS_REGIME = False

try:
    from modules.loss_prevention import LossPreventionSystem
    HAS_LOSS_PREVENTION = True
except ImportError:
    HAS_LOSS_PREVENTION = False

try:
    from modules.market_indices import MarketIndicesMonitor
    HAS_MARKET_INDICES = True
except ImportError:
    HAS_MARKET_INDICES = False

try:
    from modules.adaptive_intelligence import AdaptiveIntelligence
    HAS_ADAPTIVE = True
except ImportError:
    HAS_ADAPTIVE = False

try:
    from modules.opportunity_scanner import OpportunityScanner
    HAS_OPPORTUNITY = True
except ImportError:
    HAS_OPPORTUNITY = False

try:
    from modules.sentiment_analyzer import EnhancedSentimentAnalyzer
    HAS_SENTIMENT = True
except ImportError:
    HAS_SENTIMENT = False

logger = setup_logger('QuantumMain', 'quantum_main.log')

EST = timezone(timedelta(hours=-5))

def get_eastern_time() -> datetime:
    return datetime.now(EST)

def pprint(msg: str):
    print(msg, flush=True)
    sys.stdout.flush()


class QuantumSwingTrader:
    """v10.1 - SMART SIZING + ATR FILTER"""
    
    def __init__(self, config_path: str = 'config.json'):
        pprint("=" * 80)
        pprint("   QUANTUM TRADING SYSTEM v10.3 - GHOST FIX + SPY FADE + ATR FILTER")
        pprint("   ZERO OVERNIGHT RISK. 3 ENTRIES MAX. 1:00 PM CUTOFF.")
        pprint("   WINDOWS SLEEP PREVENTION. HARD KILL 4:05 PM.")
        pprint("=" * 80)
        
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.config
        self.reporter = init_reporter(self.config)
        
        # Core components
        pprint("[INIT] Core components...")
        self.db = QuantumDatabase(self.config.get('db_path', 'quantum.db'))
        self.data_manager = QuantumDataManager(self.config)
        self.risk_manager = QuantumRiskManager(self.config)
        self.portfolio_manager = PortfolioManager(self.config, self.db, self.risk_manager)
        self.execution_engine = ExecutionEngine(self.config, self.portfolio_manager, self.risk_manager, self.db)
        self.ml_engine = MLEngine(self.config, self.data_manager)
        
        self.pdt_tracker = PDTTracker(self.config)
        pprint(f"[INIT] PDTTracker | Day trades: {self.pdt_tracker.get_day_trades_used()}/3")
        
        # Sentiment analyzer
        self.sentiment_analyzer = None
        if HAS_SENTIMENT:
            try:
                self.sentiment_analyzer = EnhancedSentimentAnalyzer(self.config)
                pprint(f"[INIT] SentimentAnalyzer | Ready")
            except Exception as e:
                pprint(f"[INIT] SentimentAnalyzer failed: {e}")
        
        # Swing Strategy
        self.swing_strategy = SwingStrategyEngine(
            self.config, self.risk_manager, self.ml_engine, 
            self.data_manager, self.pdt_tracker, self.reporter,
            self.sentiment_analyzer
        )
        
        # Protection modules
        pprint("[INIT] Protection layers...")
        
        self.regime_detector = None
        if HAS_REGIME:
            try:
                self.regime_detector = RegimeDetector(self.config, self.data_manager)
                pprint("[INIT] + RegimeDetector")
            except Exception as e:
                pprint(f"[INIT] x RegimeDetector: {e}")
        
        self.loss_prevention = None
        if HAS_LOSS_PREVENTION:
            try:
                self.loss_prevention = LossPreventionSystem(self.config)
                pprint("[INIT] + LossPreventionSystem")
            except Exception as e:
                pprint(f"[INIT] x LossPreventionSystem: {e}")
        
        self.market_indices = None
        if HAS_MARKET_INDICES:
            try:
                self.market_indices = MarketIndicesMonitor(self.config)
                pprint("[INIT] + MarketIndicesMonitor")
            except Exception as e:
                pprint(f"[INIT] x MarketIndicesMonitor: {e}")
        
        self.adaptive_intel = None
        if HAS_ADAPTIVE:
            try:
                self.adaptive_intel = AdaptiveIntelligence(self.config, self.data_manager)
                pprint("[INIT] + AdaptiveIntelligence")
            except Exception as e:
                pprint(f"[INIT] x AdaptiveIntelligence: {e}")
        
        self.opportunity_scanner = None
        if HAS_OPPORTUNITY:
            try:
                self.opportunity_scanner = OpportunityScanner(self.config, self.data_manager)
                pprint("[INIT] + OpportunityScanner")
            except Exception as e:
                pprint(f"[INIT] x OpportunityScanner: {e}")
        
        # State
        self.running = False
        self.universe = []
        self.trades_today = 0
        self.pnl_today = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.cycle_count = 0
        self.day_start_value = None
        
        self.trading_halted = False
        self.current_regime = 'NEUTRAL'
        self.market_health = 'UNKNOWN'
        self.market_direction = 'NEUTRAL'
        self.adaptive_confidence = self.config.get('min_confidence', 0.85)
        
        # Time windows
        self.premarket_start = dtime(9, 20)
        self.market_open = dtime(9, 30)
        self.entry_start = dtime(9, 30)
        self.entry_cutoff = dtime(13, 0)       # v9.9 FIX: was 15:30, now matches swing_strategy
        self.eod_exit_time = dtime(15, 45)
        self.nuclear_eod_time = dtime(15, 55)   # v9.9: Last-resort liquidation
        self.market_close = dtime(16, 0)
        self.hard_kill_time = dtime(16, 5)      # v10.0: ABSOLUTE shutdown, no exceptions
        
        # Profit lock settings
        self.morning_profit_threshold = 0.015
        self.premarket_profit_threshold = 0.02
        self.midday_profit_threshold = 0.02
        self.midday_min_hold_minutes = 120
        self.eod_loss_threshold = -0.005
        
        # Tracking
        self.morning_profit_lock_done = False
        self.premarket_check_done = False
        self.eod_exit_done = False
        self.nuclear_eod_done = False             # v9.9: Nuclear backstop flag
        self.position_entry_times = {}
        self.entries_today = 0                     # v9.9: Hard cap - 3 entries max per day
        self.max_entries_per_day = 3               # v9.9: UNBREAKABLE LIMIT
        self.pdt_blocked_tickers = set()           # v10.1: Tickers Alpaca won't let us sell today
        self.closed_eod_tickers = set()            # v10.3: Tickers already sold at EOD (prevent ghost re-sells)
        self.last_cycle_wallclock = None           # v10.0: Detect sleep gaps
        self.sleep_prevention_active = False       # v10.0: Windows sleep prevention state
        
        self._print_startup_info()
    
    def _print_startup_info(self):
        et = get_eastern_time()
        pprint("-" * 60)
        pprint(f"Time: {et.strftime('%Y-%m-%d %H:%M:%S')} ET")
        
        try:
            account_value = self.portfolio_manager.get_portfolio_value()
            self.day_start_value = account_value
            pprint(f"Account: ${account_value:,.2f}")
        except:
            self.day_start_value = self.config.get('initial_capital', 500)
        
        pdt_status = self.pdt_tracker.get_status()
        pprint(f"PDT (internal): {pdt_status['day_trades_used']}/3 used")
        
        # v10.1: Show ACTUAL Alpaca PDT count — this is the truth
        alpaca_pdt = self._get_alpaca_daytrade_count()
        remaining = max(0, 3 - alpaca_pdt)
        pprint(f"PDT (Alpaca):   {alpaca_pdt}/3 used | {remaining} round trips available today")
        if remaining == 0:
            pprint(f"⚠️ NO DAY TRADES AVAILABLE — Bot will NOT buy today (can't sell same day)")
        elif remaining == 1:
            pprint(f"⚠️ ONLY 1 day trade left — Bot limited to 1 entry today")
        
        max_pos = self.config.get('max_positions', 3)
        pprint(f"Max Positions: {max_pos}")
        
        pprint("-" * 60)
        
        positions = self.portfolio_manager.get_positions()
        self.pdt_tracker.initialize_positions(positions)
        
        for ticker in positions:
            self.position_entry_times[ticker] = et - timedelta(hours=12)
        
        if positions:
            pprint(f"CURRENT POSITIONS: {len(positions)}/{max_pos}")
            for ticker, pos in positions.items():
                entry = pos.get('entry_price', 0)
                current = pos.get('current_price', entry)
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
                pprint(f"  {ticker}: ${entry:.2f} → ${current:.2f} ({pnl_pct:+.2f}%)")
        else:
            pprint(f"CURRENT POSITIONS: 0/{max_pos}")
        pprint("-" * 60)

    def _get_reliable_price(self, ticker: str, entry_price: float) -> Optional[float]:
        """Get reliable price from multiple sources"""
        prices = []
        
        try:
            broker = self.execution_engine.broker
            if broker:
                try:
                    trade = broker.get_latest_trade(ticker)
                    if trade and trade.price:
                        prices.append(float(trade.price))
                except:
                    pass
                
                try:
                    quote = broker.get_latest_quote(ticker)
                    if quote:
                        if quote.ask_price and float(quote.ask_price) > 0:
                            prices.append(float(quote.ask_price))
                        if quote.bid_price and float(quote.bid_price) > 0:
                            prices.append(float(quote.bid_price))
                except:
                    pass
        except:
            pass
        
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get('regularMarketPrice') or info.get('currentPrice')
            if price and price > 0:
                prices.append(float(price))
        except:
            pass
        
        if not prices:
            return None
        
        prices.sort()
        return prices[len(prices) // 2]

    # ═══════════════════════════════════════════════════════════════════
    # v10.0: WINDOWS SLEEP PREVENTION
    # ═══════════════════════════════════════════════════════════════════
    def _prevent_sleep(self):
        """Prevent Windows from sleeping during market hours.
        ES_CONTINUOUS (0x80000000) - Keep the state flags in effect
        ES_SYSTEM_REQUIRED (0x00000001) - Prevent system sleep
        ES_DISPLAY_REQUIRED (0x00000002) - Prevent display sleep
        """
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
            self.sleep_prevention_active = True
            pprint("[SLEEP] ✅ Windows sleep prevention ACTIVE - OS will NOT sleep")
        except Exception as e:
            # Not on Windows or ctypes not available — not fatal
            pprint(f"[SLEEP] ⚠️ Could not set sleep prevention: {e}")
            pprint("[SLEEP] ⚠️ Bot may be suspended if PC sleeps!")
    
    def _allow_sleep(self):
        """Re-enable Windows sleep on shutdown"""
        try:
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            self.sleep_prevention_active = False
            pprint("[SLEEP] Windows sleep prevention released")
        except:
            pass

    def run_live(self):
        self.running = True
        signal.signal(signal.SIGINT, lambda s, f: setattr(self, 'running', False))
        
        pprint(f"[START] {get_eastern_time().strftime('%H:%M:%S')} ET")
        
        # v10.0: Prevent Windows from sleeping
        self._prevent_sleep()
        
        if not self._wait_for_premarket_or_open():
            self._allow_sleep()
            return
        
        try:
            self.day_start_value = self.portfolio_manager.get_portfolio_value()
        except:
            pass
        
        if self.loss_prevention:
            self.loss_prevention.initialize_day(self.day_start_value)
        
        self.reporter.start_session({
            'portfolio_value': self.day_start_value,
            'positions': self.portfolio_manager.get_positions(),
            'cash': self.portfolio_manager.get_cash(),
            'timestamp': get_eastern_time().isoformat()
        })
        
        self._build_universe()
        
        cycle_interval = self.config.get('cycle_interval', 120)
        
        while self.running:
            et = get_eastern_time()
            now_wall = time.time()
            
            if et.weekday() >= 5:
                pprint("[MARKET] Weekend - stopping")
                break
            
            # v10.0: HARD KILL at 4:05 PM — no exceptions, no waiting
            if et.time() >= self.hard_kill_time:
                pprint(f"[HARD KILL] {et.strftime('%H:%M:%S')} ET — Past 4:05 PM, forcing shutdown!")
                # Force EOD if not done
                if not self.eod_exit_done:
                    self._eod_liquidate_all()
                    self.eod_exit_done = True
                break
            
            if et.time() > self.market_close:
                pprint("[MARKET] Closed for the day")
                break
            
            # v10.0: SLEEP GAP DETECTION — if >5 min since last cycle, something froze
            if self.last_cycle_wallclock is not None:
                gap_seconds = now_wall - self.last_cycle_wallclock
                if gap_seconds > 300:  # 5 minutes
                    gap_minutes = gap_seconds / 60
                    pprint(f"")
                    pprint(f"  ⚠️⚠️⚠️ SLEEP GAP DETECTED: {gap_minutes:.1f} minutes since last cycle! ⚠️⚠️⚠️")
                    pprint(f"  PC likely went to sleep. Current time: {et.strftime('%H:%M:%S')} ET")
                    
                    # If we woke up past EOD time, force liquidation NOW
                    if et.time() >= self.eod_exit_time and not self.eod_exit_done:
                        pprint(f"  >>> MISSED EOD WINDOW! Forcing immediate liquidation!")
                        self._eod_liquidate_all()
                        self.eod_exit_done = True
                    
                    # If past market close, just break
                    if et.time() >= self.market_close:
                        pprint(f"  >>> Past market close, shutting down.")
                        break
            
            if self.premarket_start <= et.time() < self.market_open:
                if not self.premarket_check_done:
                    self._check_premarket_exits()
                time.sleep(30)
                self.last_cycle_wallclock = time.time()
                continue
            
            if et.time() >= self.market_open and not self.morning_profit_lock_done:
                pprint("[MARKET] Market OPEN - checking morning profit lock...")
                time.sleep(5)
                self._check_morning_profit_lock()
                self.morning_profit_lock_done = True
            
            if et.time() >= self.eod_exit_time and not self.eod_exit_done:
                self._eod_liquidate_all()
                self.eod_exit_done = True
            
            # v9.9: NUCLEAR EOD at 3:55 PM - absolute last resort
            if et.time() >= self.nuclear_eod_time and not self.nuclear_eod_done:
                self._nuclear_eod_liquidation()
                self.nuclear_eod_done = True
            
            if self._is_market_open():
                try:
                    self._run_cycle()
                    self.cycle_count += 1
                    
                    current_value = self.portfolio_manager.get_portfolio_value()
                    daily_pnl = current_value - self.day_start_value if self.day_start_value else 0
                    positions = self.portfolio_manager.get_positions()
                    max_pos = self.config.get('max_positions', 3)
                    
                    status_icon = "🟢" if daily_pnl >= 0 else "🔴"
                    pprint(f"[CYCLE {self.cycle_count}] {status_icon} ${current_value:.2f} | Day:${daily_pnl:+.2f} | Pos:{len(positions)}/{max_pos} | E:{self.entries_today}/{self.max_entries_per_day} | W{self.winning_trades}/L{self.losing_trades}")
                    
                    try:
                        self.reporter.log_cycle({
                            'cycle': self.cycle_count,
                            'time': et.isoformat(),
                            'portfolio_value': current_value,
                            'daily_pnl': daily_pnl,
                            'regime': self.current_regime,
                            'positions_count': len(positions)
                        })
                    except:
                        pass
                    
                    self.last_cycle_wallclock = time.time()
                    time.sleep(cycle_interval)
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    pprint(f"[ERROR] Cycle error: {e}")
                    import traceback
                    traceback.print_exc()
                    self.last_cycle_wallclock = time.time()
                    time.sleep(30)
            else:
                self.last_cycle_wallclock = time.time()
                time.sleep(30)
        
        self._shutdown()

    def _wait_for_premarket_or_open(self) -> bool:
        et = get_eastern_time()
        
        if et.weekday() >= 5:
            pprint("[MARKET] Weekend")
            return False
        
        if et.time() > self.market_close:
            pprint("[MARKET] Closed")
            return False
        
        if et.time() < self.premarket_start:
            pprint(f"[MARKET] Waiting for pre-market ({self.premarket_start})...")
            while get_eastern_time().time() < self.premarket_start:
                if not self.running:
                    return False
                time.sleep(30)
        
        return True

    def _check_premarket_exits(self):
        et = get_eastern_time()
        pprint(f"\n[PRE-MARKET] {et.strftime('%H:%M:%S')} ET")
        
        positions = self.portfolio_manager.get_positions()
        if not positions:
            pprint("[PRE-MARKET] No positions")
            self.premarket_check_done = True
            return
        
        for ticker, pos in positions.items():
            entry_price = float(pos.get('entry_price', 0))
            if entry_price <= 0:
                continue
            
            current_price = self._get_reliable_price(ticker, entry_price)
            if current_price:
                pnl_pct = (current_price - entry_price) / entry_price
                pprint(f"[PRE-MARKET] {ticker}: ${current_price:.2f} ({pnl_pct*100:+.2f}%)")
        
        self.premarket_check_done = True

    def _check_morning_profit_lock(self):
        positions = self.portfolio_manager.get_positions()
        
        if not positions:
            pprint("[MORNING] No positions")
            return
        
        for ticker, pos in positions.items():
            entry_price = float(pos.get('entry_price', 0))
            quantity = int(pos.get('quantity', 0))
            
            if entry_price <= 0:
                continue
            
            current_price = self._get_reliable_price(ticker, entry_price)
            if not current_price:
                current_price = float(pos.get('current_price', 0))
            
            if current_price <= 0:
                continue
            
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollars = (current_price - entry_price) * quantity
            
            pprint(f"[MORNING] {ticker}: {pnl_pct*100:+.2f}% (${pnl_dollars:+.2f})")
            
            if pnl_pct >= self.morning_profit_threshold:
                pprint(f"[MORNING] >>> PROFIT LOCK {ticker}!")
                self._force_sell(ticker, quantity, current_price, entry_price, "MORNING_PROFIT_LOCK")

    def _eod_liquidate_all(self):
        """
        v9.9: CLOSE ALL POSITIONS AT EOD — not just losers!
        v9.8 bug: only closed positions below eod_loss_threshold.
        Now closes EVERYTHING. Zero overnight risk, no exceptions.
        """
        et = get_eastern_time()
        pprint(f"")
        pprint(f"  🔴🔴🔴 EOD LIQUIDATION — {et.strftime('%H:%M:%S')} ET 🔴🔴🔴")
        pprint(f"  Closing ALL positions. Zero overnight exposure.")
        pprint(f"")
        
        positions = self.portfolio_manager.get_positions()
        if not positions:
            pprint(f"  ✅ No positions to liquidate — clean EOD!")
            return
        
        pprint(f"  Found {len(positions)} position(s) to close:")
        
        failed_tickers = []
        
        for ticker, pos in positions.items():
            # v10.3: Skip tickers already successfully sold (prevent ghost re-sells)
            if ticker in self.closed_eod_tickers:
                pprint(f"  [SKIP] {ticker} already sold this session — skipping ghost position")
                continue
            
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = int(pos.get('quantity', 0))
            
            if entry_price <= 0 or quantity <= 0:
                continue
            
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollars = (current_price - entry_price) * quantity
            icon = "🟢" if pnl_pct >= 0 else "🔴"
            
            pprint(f"  {icon} {ticker}: {pnl_pct*100:+.2f}% (${pnl_dollars:+.2f}) >>> FORCE CLOSE")
            
            success = self._force_sell(ticker, quantity, current_price, entry_price, "EOD_LIQUIDATE_ALL")
            if not success:
                failed_tickers.append(ticker)
                if ticker in self.pdt_blocked_tickers:
                    pprint(f"  🚫 {ticker} is PDT-blocked — forced overnight hold")
                else:
                    pprint(f"  ❌ FAILED to close {ticker} — will retry in nuclear phase!")
        
        # Verify all positions closed
        time.sleep(1)
        remaining = self.portfolio_manager.get_positions()
        # v10.3: Filter out tickers we already successfully sold (Alpaca settlement delay)
        remaining = {t: p for t, p in remaining.items() if t not in self.closed_eod_tickers}
        if remaining:
            pprint(f"")
            pprint(f"  ⚠️ WARNING: {len(remaining)} position(s) still open after EOD liquidation!")
            pprint(f"  Remaining: {list(remaining.keys())}")
            pprint(f"  Nuclear backstop at 3:55 PM will handle these.")
        else:
            pprint(f"")
            pprint(f"  ✅ ALL positions closed — clean EOD confirmed!")

    def _nuclear_eod_liquidation(self):
        """
        v10.0: ABSOLUTE LAST RESORT at 3:55 PM.
        Now re-queries ACTUAL broker positions to prevent double-sells.
        v9.9 bug: used cached positions, sold T twice (EOD + Nuclear).
        
        RULE: We NEVER hold overnight. Period.
        """
        et = get_eastern_time()
        
        # v10.0: Force refresh positions from broker (not cache!)
        try:
            self.portfolio_manager._refresh_positions()
        except:
            pass
        
        positions = self.portfolio_manager.get_positions()
        if not positions:
            pprint(f"[NUCLEAR] 3:55 PM — No positions, skipping.")
            return
        
        pprint(f"")
        pprint(f"  ☢️☢️☢️ NUCLEAR EOD — {et.strftime('%H:%M:%S')} ET ☢️☢️☢️")
        pprint(f"  {len(positions)} position(s) STILL OPEN after normal EOD!")
        pprint(f"  Executing broker-level close_all_positions()...")
        pprint(f"")
        
        # Method 1: Broker's close_all_positions
        try:
            result = self.portfolio_manager.close_all_positions()
            if result:
                pprint(f"  ☢️ NUCLEAR: broker.close_all_positions() returned SUCCESS")
            else:
                pprint(f"  ☢️ NUCLEAR: broker.close_all_positions() returned FAILURE")
        except Exception as e:
            pprint(f"  ☢️ NUCLEAR: broker.close_all_positions() ERROR: {e}")
        
        # Method 2: Also cancel all open orders
        try:
            self.portfolio_manager.cancel_all_orders()
            pprint(f"  ☢️ NUCLEAR: All open orders cancelled")
        except Exception as e:
            pprint(f"  ☢️ NUCLEAR: Cancel orders error: {e}")
        
        # Method 3: Individual force sells for each remaining position
        # v10.0: Re-query ACTUAL broker positions before individual sells
        time.sleep(2)
        try:
            self.portfolio_manager._refresh_positions()
        except:
            pass
        remaining = self.portfolio_manager.get_positions()
        if remaining:
            pprint(f"  ☢️ NUCLEAR: {len(remaining)} STILL OPEN! Attempting individual force sells...")
            for ticker, pos in remaining.items():
                # v10.3: Skip tickers already successfully sold (prevent ghost re-sells)
                if ticker in self.closed_eod_tickers:
                    pprint(f"  ☢️ NUCLEAR: [SKIP] {ticker} already sold — ghost position in cache")
                    continue
                try:
                    quantity = int(pos.get('quantity', 0))
                    entry_price = float(pos.get('entry_price', 0))
                    current_price = float(pos.get('current_price', 0))
                    if quantity > 0:
                        self._force_sell(ticker, quantity, current_price, entry_price, "NUCLEAR_EOD")
                except Exception as e:
                    pprint(f"  ☢️ NUCLEAR: Failed to force-sell {ticker}: {e}")
        
        # Final verification
        time.sleep(2)
        try:
            self.portfolio_manager._refresh_positions()
        except:
            pass
        final_check = self.portfolio_manager.get_positions()
        # v10.3: Filter out tickers we already successfully sold (Alpaca settlement delay)
        final_check = {t: p for t, p in final_check.items() if t not in self.closed_eod_tickers}
        if final_check:
            pdt_held = [t for t in final_check if t in self.pdt_blocked_tickers]
            other_held = [t for t in final_check if t not in self.pdt_blocked_tickers]
            
            if pdt_held:
                pprint(f"")
                pprint(f"  🚫 PDT OVERNIGHT HOLD: {pdt_held}")
                pprint(f"  These positions cannot be sold today due to PDT protection.")
                pprint(f"  They will be sold at market open tomorrow (NOT a day trade).")
            
            if other_held:
                pprint(f"")
                pprint(f"  ❌❌❌ CRITICAL: {len(other_held)} NON-PDT POSITIONS SURVIVED! ❌❌❌")
                pprint(f"  Tickers: {other_held}")
                pprint(f"  MANUAL INTERVENTION REQUIRED!")
            
            if not other_held:
                pprint(f"  ✅ All remaining positions are PDT holds — expected behavior.")
        else:
            pprint(f"  ✅ NUCLEAR EOD: All positions confirmed closed.")

    def _force_sell(self, ticker: str, quantity: int, current_price: float, 
                    entry_price: float, reason: str) -> bool:
        """
        FORCE a sell to go through - used for stop losses and critical exits.
        v10.1: Now detects PDT blocks and stops retrying.
        """
        # v10.1: Skip if already PDT-blocked today
        if ticker in self.pdt_blocked_tickers:
            pprint(f"  [SKIP] {ticker} is PDT-blocked — will hold overnight")
            return False
        
        pprint(f"")
        pprint(f"  ⚠️⚠️⚠️ FORCE SELL: {ticker} ⚠️⚠️⚠️")
        pprint(f"  Reason: {reason}")
        pprint(f"  Quantity: {quantity} @ ${current_price:.2f}")
        
        pnl_dollars = (current_price - entry_price) * quantity
        pprint(f"  Expected P&L: ${pnl_dollars:+.2f}")
        
        success = False
        actual_pnl = pnl_dollars
        pdt_blocked = False
        
        # Method 1: execution_engine.force_close_position
        pprint(f"  [ATTEMPT 1] Using execution_engine.force_close_position...")
        try:
            result = self.execution_engine.force_close_position(ticker)
            if result and result.get('success'):
                success = True
                actual_pnl = result.get('pnl', pnl_dollars)
                pprint(f"  [ATTEMPT 1] ✅ SUCCESS! P&L: ${actual_pnl:+.2f}")
        except Exception as e:
            error_str = str(e).lower()
            pprint(f"  [ATTEMPT 1] ❌ FAILED: {e}")
            if 'pattern day trad' in error_str:
                pdt_blocked = True
        
        # Method 2: Direct broker order (skip if PDT blocked)
        if not success and not pdt_blocked:
            pprint(f"  [ATTEMPT 2] Using direct broker.submit_order...")
            try:
                broker = self.execution_engine.broker
                if broker:
                    order = broker.submit_order(
                        symbol=ticker, 
                        qty=quantity, 
                        side='sell',
                        type='market', 
                        time_in_force='day'
                    )
                    pprint(f"  [ATTEMPT 2] Order submitted: {order.id}")
                    
                    # Wait for fill
                    for _ in range(10):
                        time.sleep(0.5)
                        updated = broker.get_order(order.id)
                        pprint(f"  [ATTEMPT 2] Order status: {updated.status}")
                        if updated.status == 'filled':
                            fill_price = float(updated.filled_avg_price)
                            actual_pnl = (fill_price - entry_price) * quantity
                            success = True
                            pprint(f"  [ATTEMPT 2] ✅ FILLED @ ${fill_price:.2f} | P&L: ${actual_pnl:+.2f}")
                            break
                        elif updated.status in ['cancelled', 'rejected', 'expired']:
                            pprint(f"  [ATTEMPT 2] ❌ Order {updated.status}")
                            break
                else:
                    pprint(f"  [ATTEMPT 2] ❌ No broker connection!")
            except Exception as e:
                error_str = str(e).lower()
                pprint(f"  [ATTEMPT 2] ❌ FAILED: {e}")
                if 'pattern day trad' in error_str:
                    pdt_blocked = True
        
        # v10.1: Handle PDT block gracefully
        if pdt_blocked and not success:
            self.pdt_blocked_tickers.add(ticker)
            pprint(f"")
            pprint(f"  🚫🚫🚫 PDT BLOCK: {ticker} cannot be sold today 🚫🚫🚫")
            pprint(f"  Alpaca denied sell due to Pattern Day Trading protection.")
            pprint(f"  {ticker} will be held OVERNIGHT and sold tomorrow.")
            pprint(f"  Unrealized P&L: ${pnl_dollars:+.2f}")
            pprint(f"  This ticker is now marked — no more sell attempts today.")
            return False
        
        # Record the trade
        if success:
            self.trades_today += 1
            self.pnl_today += actual_pnl
            
            if actual_pnl >= 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1
            
            self.pdt_tracker.record_sell(ticker)
            self.swing_strategy.record_exit(ticker, actual_pnl)
            self.position_entry_times.pop(ticker, None)
            self.closed_eod_tickers.add(ticker)  # v10.3: Prevent ghost re-sells
            
            if self.loss_prevention:
                self.loss_prevention.record_trade_result(actual_pnl)
            
            self.reporter.log_trade({
                'ticker': ticker, 'action': 'SELL', 'quantity': quantity,
                'price': current_price, 'pnl': actual_pnl, 'reason': reason
            })
            
            pprint(f"  ✅ SELL COMPLETE: {ticker} | P&L: ${actual_pnl:+.2f}")
        else:
            pprint(f"  ❌❌❌ SELL FAILED FOR {ticker}! This is a critical error! ❌❌❌")
        
        pprint(f"")
        return success

    # ═══════════════════════════════════════════════════════════════════════
    # v10.1: ALPACA PDT SYNC — Query broker's ACTUAL day trade count
    # Our internal tracker was blind to Alpaca's rolling 5-day window.
    # This caused AKAM sell blocked on Mar 3 — bot couldn't sell a winner.
    # ═══════════════════════════════════════════════════════════════════════
    def _get_alpaca_daytrade_count(self) -> int:
        """Query Alpaca API for ACTUAL rolling 5-day day trade count.
        Returns the count, or 99 on error (block all entries if we can't check)."""
        try:
            broker = self.execution_engine.broker
            if broker:
                account = broker.get_account()
                count = int(account.daytrade_count)
                return count
            else:
                pprint(f"  [PDT] ⚠️ No broker — assuming max PDT count")
                return 99
        except Exception as e:
            pprint(f"  [PDT] ⚠️ Could not query Alpaca PDT count: {e}")
            return 99  # Safe fallback: block entries if we can't check
    
    def _get_remaining_day_trades(self) -> int:
        """How many more same-day round trips can we do today?
        Each BUY we make today MUST be sellable same-day, so we need:
        remaining = 3 - alpaca_daytrade_count"""
        alpaca_count = self._get_alpaca_daytrade_count()
        remaining = max(0, 3 - alpaca_count)
        return remaining

    def _run_cycle(self):
        et = get_eastern_time()
        
        pprint("")
        pprint("=" * 70)
        pprint(f"  CYCLE {self.cycle_count + 1} | {et.strftime('%H:%M:%S')} ET")
        pprint("=" * 70)
        
        # Layer 1: Regime
        if self.regime_detector:
            try:
                regime, confidence, _ = self.regime_detector.update()
                self.current_regime = regime
                pprint(f"[REGIME] {regime} ({confidence:.0%})")
            except Exception as e:
                self.current_regime = 'NEUTRAL'
        
        # Layer 2: Loss Prevention
        current_value = self.portfolio_manager.get_portfolio_value()
        positions = self.portfolio_manager.get_positions()
        
        if self.loss_prevention:
            try:
                lp = self.loss_prevention.update(current_value, positions)
                if lp.get('action') == 'HALT_AND_LIQUIDATE':
                    pprint(f"[LOSS] >>> HALT! {lp.get('reason')}")
                    self.trading_halted = True
                    return
            except:
                pass
        
        if self.trading_halted:
            return
        
        # Layer 3: Market Health
        if self.market_indices:
            try:
                self.market_indices.fetch_all_indices()
                breadth = self.market_indices.get_market_breadth()
                self.market_health = breadth.get('state', 'UNKNOWN')
            except:
                pass
        
        # Update strategy with current positions
        self.swing_strategy.update_positions(positions)
        
        # v10.3: Query ACTUAL Alpaca PDT count BEFORE generating signals
        # The internal pdt_tracker was corrupted by ghost triple-sells on Mar 13.
        # Alpaca is the ONLY source of truth for day trade count.
        alpaca_count = self._get_alpaca_daytrade_count()
        alpaca_remaining = max(0, 3 - alpaca_count)
        
        # Generate signals — pass Alpaca remaining so swing_strategy uses it
        filtered_universe = self.universe.copy()
        all_signals = self.swing_strategy.generate_signals(filtered_universe, alpaca_remaining=alpaca_remaining)
        
        exit_signals = [s for s in all_signals if s.get('is_exit')]
        entry_signals = [s for s in all_signals if not s.get('is_exit')]
        
        entry_signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        pprint(f"[SIGNALS] {len(exit_signals)} exits, {len(entry_signals)} entries")
        
        # ═══════════════════════════════════════════════════════════════════
        # PROCESS EXITS FIRST - THIS IS CRITICAL!
        # ═══════════════════════════════════════════════════════════════════
        if exit_signals:
            pprint(f"")
            pprint(f"  🚨🚨🚨 PROCESSING {len(exit_signals)} EXIT SIGNALS 🚨🚨🚨")
            
            for sig in exit_signals:
                ticker = sig.get('ticker')
                reason = sig.get('reason', 'SIGNAL_EXIT')
                pnl_pct = sig.get('pnl_pct', 0)
                
                # v10.1: Skip PDT-blocked tickers immediately (no log spam)
                if ticker in self.pdt_blocked_tickers:
                    continue
                
                # v10.3: Skip tickers already sold this session (ghost position fix)
                if ticker in self.closed_eod_tickers:
                    continue
                
                pprint(f"")
                pprint(f"  [EXIT SIGNAL] {ticker}")
                pprint(f"    Reason: {reason}")
                pprint(f"    P&L %: {pnl_pct*100:.2f}%")
                
                if ticker not in positions:
                    pprint(f"    ❌ SKIP: {ticker} not in current positions!")
                    pprint(f"    Current positions: {list(positions.keys())}")
                    continue
                
                pos = positions[ticker]
                quantity = int(pos.get('quantity', 0))
                entry_price = float(pos.get('entry_price', 0))
                current_price = float(pos.get('current_price', 0))
                
                # Check if this is a STOP LOSS - if so, FORCE it through!
                is_stop_loss = 'STOP_LOSS' in reason or 'CATASTROPHIC' in reason
                
                if is_stop_loss:
                    pprint(f"    ⚠️ STOP LOSS DETECTED - FORCING EXECUTION!")
                    # FORCE SELL - Don't check PDT for stop losses!
                    self._force_sell(ticker, quantity, current_price, entry_price, reason)
                else:
                    # Normal exit - check PDT using ALPACA (source of truth)
                    # v10.3 CRITICAL: Internal pdt_tracker was corrupted by Friday's
                    # ghost triple-sells, showing 0 remaining when Alpaca showed 1.
                    # This blocked ALL profit-taking sells from cycle 80-141,
                    # turning a +$0.38 win into a -$0.66 loss.
                    # 
                    # Logic: Selling a position bought TODAY uses a day trade.
                    # Selling an overnight position is FREE (no day trade).
                    is_today_position = ticker in self.swing_strategy.positions_bought_today
                    
                    if is_today_position and alpaca_remaining <= 0:
                        # Bought today + no day trades left = genuinely PDT blocked
                        pprint(f"    PDT Check: ❌ BLOCKED - Alpaca: {alpaca_count}/3 used, 0 remaining (bought today)")
                        pprint(f"    (Note: This is NOT a stop loss, so PDT rules apply)")
                    else:
                        # Either overnight position (free sell) or we have day trades remaining
                        if is_today_position:
                            pprint(f"    PDT Check: ✅ Allowed (Alpaca: {alpaca_remaining} day trades remaining)")
                        else:
                            pprint(f"    PDT Check: ✅ Allowed (overnight position — free sell)")
                        self._force_sell(ticker, quantity, current_price, entry_price, reason)
        
        # Refresh positions after exits
        positions = self.portfolio_manager.get_positions()
        pos_count = len(positions)
        max_positions = self.config.get('max_positions', 3)
        cash = self.portfolio_manager.get_cash()
        
        # Check profit preservation
        if self.swing_strategy.is_profit_preservation_active():
            pprint(f"")
            pprint(f"  🛡️ PROFIT PRESERVATION ACTIVE - Skipping entries")
            return
        
        # Entry logic
        pprint(f"")
        pprint(f"[ENTRY CHECK] ══════════════════════════════════════════")
        pprint(f"  Positions: {pos_count}/{max_positions}")
        pprint(f"  Entries today: {self.entries_today}/{self.max_entries_per_day}")
        pprint(f"  Cash: ${cash:.2f}")
        
        # v10.3: Reuse Alpaca PDT count already queried before generate_signals
        # (alpaca_count and alpaca_remaining set above — no duplicate API call)
        remaining_day_trades = alpaca_remaining
        pprint(f"  Alpaca PDT: {alpaca_count}/3 used (rolling 5-day) | {remaining_day_trades} remaining")
        
        entries_blocked = False
        block_reason = None
        
        # v10.1: ALPACA PDT CHECK — checked FIRST, absolute authority
        if remaining_day_trades <= 0:
            entries_blocked = True
            block_reason = f"ALPACA PDT LIMIT: {alpaca_count}/3 day trades used (rolling 5-day). Cannot buy — would be unable to sell today."
        # v9.9: Hard entries cap
        elif self.entries_today >= self.max_entries_per_day:
            entries_blocked = True
            block_reason = f"HARD CAP: {self.entries_today}/{self.max_entries_per_day} entries used today"
        elif et.time() < self.entry_start:
            entries_blocked = True
            block_reason = f"Before market open ({self.entry_start})"
        elif et.time() >= self.entry_cutoff:
            entries_blocked = True
            block_reason = f"After entry cutoff ({self.entry_cutoff})"
        elif self.current_regime in ['CRASH', 'RISK_OFF']:
            entries_blocked = True
            block_reason = f"Bad regime ({self.current_regime})"
        elif pos_count >= max_positions:
            entries_blocked = True
            block_reason = f"Max positions reached ({pos_count}/{max_positions})"
        elif cash < 50:
            entries_blocked = True
            block_reason = f"Insufficient cash (${cash:.2f})"
        
        if entries_blocked:
            pprint(f"  >>> ENTRIES BLOCKED: {block_reason}")
        else:
            pprint(f"  >>> ENTRIES ALLOWED ✓")
            
            if entry_signals:
                slots_available = max_positions - pos_count
                # v10.1: Also cap by remaining Alpaca day trades
                slots_available = min(slots_available, remaining_day_trades)
                pprint(f"  >>> {slots_available} slot(s) available (PDT-capped)")
                
                entries_made = 0
                for sig in entry_signals:
                    if entries_made >= slots_available:
                        break
                    
                    ticker = sig.get('ticker', 'UNKNOWN')
                    conf = sig.get('confidence', 0)
                    price = sig.get('price', 0)
                    
                    if ticker in positions:
                        continue
                    
                    # Check blocks
                    is_blocked, block_reason = self.swing_strategy.is_blocked(ticker)
                    if is_blocked:
                        pprint(f"  [SKIP] {ticker}: {block_reason}")
                        continue
                    
                    is_winner_blocked, winner_reason = self.swing_strategy.is_daily_winner_blocked(ticker)
                    if is_winner_blocked:
                        pprint(f"  [SKIP] {ticker}: {winner_reason}")
                        continue
                    
                    pprint(f"")
                    pprint(f"  [ATTEMPTING] {ticker} @ ${price:.2f} | {conf:.0%} confidence")
                    
                    result = self._execute_entry(ticker, sig)
                    
                    if result:
                        entries_made += 1
                        positions = self.portfolio_manager.get_positions()
                        pprint(f"  [SUCCESS] Now have {len(positions)}/{max_positions} positions")
                    else:
                        pprint(f"  [FAILED] Entry failed for {ticker}")
            else:
                pprint(f"  >>> No entry signals available")
        
        pprint(f"══════════════════════════════════════════════════════")

    def _execute_entry(self, ticker: str, sig: Dict) -> bool:
        try:
            # v9.9: HARD CAP — 3 entries per day, no exceptions
            if self.entries_today >= self.max_entries_per_day:
                pprint(f"    [SKIP] HARD CAP: {self.entries_today}/{self.max_entries_per_day} entries used today")
                return False
            
            price = sig.get('price')
            
            if price is None or float(price) <= 0:
                pprint(f"    [SKIP] Invalid price for {ticker}")
                return False
            
            price = float(price)
            
            # v9.9: RE-VALIDATE PRICE — ensure data is fresh before committing capital
            try:
                fresh_price = self._get_reliable_price(ticker, price)
                if fresh_price and fresh_price > 0:
                    price_drift = abs(fresh_price - price) / price
                    if price_drift > 0.01:  # More than 1% drift since scan
                        pprint(f"    [SKIP] Price drifted {price_drift*100:.2f}% since scan (${price:.2f} → ${fresh_price:.2f})")
                        return False
                    price = fresh_price  # Use fresh price for order
                    pprint(f"    [PRICE] Re-validated: ${price:.2f} (drift: {price_drift*100:.3f}%)")
                else:
                    pprint(f"    [WARN] Could not re-validate price — using scan price ${price:.2f}")
            except Exception as e:
                pprint(f"    [WARN] Price re-validation error: {e} — using scan price ${price:.2f}")
            
            portfolio_value = self.portfolio_manager.get_portfolio_value()
            cash = self.portfolio_manager.get_cash()
            
            # v10.1: Increased from 0.20 → 0.33 to unlock stocks up to ~$165
            # With $500 capital, 20% = $100 max → couldn't buy ABNB, AMT, etc.
            # Force minimum 0.33 even if config says 0.20 (config may be outdated)
            base_pct = max(0.33, self.config.get('swing_position_size', 0.33))
            target_value = portfolio_value * base_pct
            qty = int(target_value / price)
            
            # v10.1: If target says 0 shares but we CAN afford 1, buy 1
            # This prevents passing on good signals just because position sizing rounds down
            if qty <= 0 and price <= cash * 0.90:
                qty = 1
            
            max_qty = int(cash * 0.90 / price)
            qty = min(qty, max_qty)
            
            if qty <= 0:
                pprint(f"    [SKIP] Can't afford {ticker} (price=${price:.2f}, cash=${cash:.2f})")
                return False
            
            confidence = sig.get('confidence', 0)
            strategy = sig.get('strategy', 'swing')
            
            pprint(f"    [BUY] {ticker}: {qty} shares @ ${price:.2f}")
            pprint(f"           Value: ${qty * price:.2f} | Confidence: {confidence:.0%}")
            pprint(f"           Entry #{self.entries_today + 1}/{self.max_entries_per_day}")
            
            result = self.execution_engine.execute_entry(
                ticker=ticker, quantity=qty, price=price,
                strategy=strategy, direction=1
            )
            
            if result and result.get('success'):
                self.trades_today += 1
                self.entries_today += 1  # v9.9: Track entries against hard cap
                self.pdt_tracker.record_buy(ticker)
                self.swing_strategy.record_entry(ticker, price)
                self.position_entry_times[ticker] = get_eastern_time()
                
                self.reporter.log_trade({
                    'ticker': ticker, 'action': 'BUY', 'quantity': qty,
                    'price': price, 'strategy': strategy
                })
                
                pprint(f"    [BUY] >>> ✅ SUCCESS! (Entry {self.entries_today}/{self.max_entries_per_day})")
                time.sleep(0.5)
                return True
            else:
                error = result.get('error', 'Unknown') if result else 'No result'
                pprint(f"    [BUY] >>> ❌ FAILED: {error}")
                return False
                
        except Exception as e:
            pprint(f"    [BUY] >>> ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _build_universe(self):
        pprint("[UNIVERSE] Building...")
        try:
            import pandas as pd
            from io import StringIO
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            tables = pd.read_html(StringIO(response.text))
            raw = [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
            self.universe = raw[:self.config.get('max_universe_size', 100)]
            pprint(f"[UNIVERSE] {len(self.universe)} tickers")
        except Exception as e:
            self.universe = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD',
                           'JPM', 'V', 'JNJ', 'UNH', 'HD', 'PG', 'MA', 'BAC', 'XOM', 'PFE']
            pprint(f"[UNIVERSE] Fallback: {len(self.universe)}")

    def _is_market_open(self) -> bool:
        et = get_eastern_time()
        return et.weekday() < 5 and self.market_open <= et.time() <= self.market_close

    def _shutdown(self):
        pprint("")
        pprint("=" * 60)
        pprint("SESSION COMPLETE - v10.3")
        pprint("=" * 60)
        
        # v10.0: CRITICAL — refresh positions from broker (not cache!)
        try:
            try:
                self.portfolio_manager._refresh_positions()
            except:
                pass
            final_positions = self.portfolio_manager.get_positions()
            # v10.3: Filter out tickers already sold (Alpaca settlement delay shows ghosts)
            final_positions = {t: p for t, p in final_positions.items() if t not in self.closed_eod_tickers}
            if final_positions:
                pprint(f"")
                pprint(f"  ⚠️ SHUTDOWN: {len(final_positions)} position(s) STILL OPEN!")
                pprint(f"  Running emergency liquidation before shutdown...")
                self._nuclear_eod_liquidation()
                time.sleep(3)
                try:
                    self.portfolio_manager._refresh_positions()
                except:
                    pass
                final_positions = self.portfolio_manager.get_positions()
                # v10.3: Filter ghosts again after nuclear
                final_positions = {t: p for t, p in final_positions.items() if t not in self.closed_eod_tickers}
                if final_positions:
                    pprint(f"  ❌ SHUTDOWN ALERT: {len(final_positions)} survived! MANUAL CLOSE NEEDED!")
                    pprint(f"  Tickers: {list(final_positions.keys())}")
                else:
                    pprint(f"  ✅ Emergency shutdown liquidation succeeded")
            else:
                pprint(f"  ✅ No open positions at shutdown — clean exit")
        except Exception as e:
            pprint(f"  ⚠️ Error checking positions at shutdown: {e}")
        
        # v10.0: Release Windows sleep prevention
        self._allow_sleep()
        
        try:
            final_value = self.portfolio_manager.get_portfolio_value()
        except:
            final_value = self.day_start_value or 0
        
        daily_pnl = (final_value - self.day_start_value) if self.day_start_value else 0
        
        pprint(f"Trades: {self.trades_today} | W:{self.winning_trades} L:{self.losing_trades}")
        pprint(f"Entries: {self.entries_today}/{self.max_entries_per_day}")
        pprint(f"Daily P&L: ${daily_pnl:+,.2f}")
        pprint(f"Final: ${final_value:,.2f}")
        
        if daily_pnl >= 0:
            pprint("🟢 GREEN DAY ✓")
        else:
            pprint("🔴 RED DAY")
        
        self.reporter.end_session({
            'portfolio_value': final_value,
            'daily_pnl': daily_pnl
        }, {
            'trades': self.trades_today,
            'wins': self.winning_trades,
            'losses': self.losing_trades,
            'pnl': self.pnl_today
        })
        
        try:
            self.reporter.generate_report()
        except:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['live', 'backtest'], default='live')
    parser.add_argument('--config', default='config.json')
    args = parser.parse_args()
    
    system = QuantumSwingTrader(args.config)
    if args.mode == 'live':
        system.run_live()


if __name__ == "__main__":
    main()
