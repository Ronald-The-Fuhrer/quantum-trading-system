"""
SWING STRATEGY ENGINE v3.7 - PDT-SMART DAY TRADER
═══════════════════════════════════════════════════════════════════════════════

GOAL: End EVERY day GREEN. Never hold overnight. Never violate PDT.

PDT RULES:
- 3 day trades per 5 rolling days
- Day trade = BUY + SELL same stock same day
- Selling OVERNIGHT positions = NOT a day trade!

SMART LOGIC:
1. MORNING: Dump overnight losers (FREE - no day trade used!)
2. NEW BUYS: Limited to day_trades_remaining (ensures EOD liquidation works)
3. EOD: Liquidate ALL positions (overnight = free, today's = uses day trades)

EXAMPLE:
- Start with 2 overnight positions, 3 day trades available
- 9:30 AM: Sell 2 overnight losers (0 day trades used - they're from yesterday!)
- 10:00 AM: Buy 3 new positions (we have 3 day trades available)
- 3:45 PM: Sell 3 positions (uses 3 day trades)
- End: $0 positions, 0 day trades remaining, GREEN DAY ✓

═══════════════════════════════════════════════════════════════════════════════
"""
import sys
import os
import json
import logging
import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Set
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5))

def pprint(msg: str):
    print(msg, flush=True)
    sys.stdout.flush()


class SwingStrategyEngine:
    """SWING STRATEGY ENGINE v3.7 - PDT-SMART DAY TRADER"""
    
    def __init__(self, config: Dict, risk_manager=None, ml_engine=None, 
                 data_manager=None, pdt_tracker=None, reporter=None,
                 sentiment_analyzer=None):
        self.config = config
        self.risk_manager = risk_manager
        self.ml_engine = ml_engine
        self.data_manager = data_manager
        self.pdt_tracker = pdt_tracker
        self.reporter = reporter
        self.sentiment_analyzer = sentiment_analyzer
        
        # Profit targets
        self.min_confidence = config.get('min_confidence', 0.85)
        self.take_profit_pct = config.get('swing_take_profit_pct', 0.035)
        self.stop_loss_pct = config.get('swing_stop_loss_pct', 0.025)
        
        # ═══════════════════════════════════════════════════════════════════
        # PDT-SMART POSITION TRACKING
        # ═══════════════════════════════════════════════════════════════════
        self.positions_bought_today: Set[str] = set()  # Track what we bought TODAY
        self.today_date: Optional[datetime] = None
        self.max_day_trades = 3  # PDT limit
        
        # ═══════════════════════════════════════════════════════════════════
        # PROFIT PRESERVATION MODE
        # ═══════════════════════════════════════════════════════════════════
        self.profit_preservation_threshold = config.get('profit_preservation_threshold', 5.00)
        self.daily_realized_profit = 0.0
        self.profit_preservation_active = False
        self.profit_preservation_date = None
        
        # ═══════════════════════════════════════════════════════════════════
        # LOSER BLOCK LIST (7-day)
        # ═══════════════════════════════════════════════════════════════════
        self.loser_block_days = 7
        self.loser_block_file = config.get('loser_block_file', 'data/loser_block_list.json')
        self.loser_block_list = {}
        self._load_loser_block_list()
        
        # ═══════════════════════════════════════════════════════════════════
        # DAILY WINNER BLOCK
        # ═══════════════════════════════════════════════════════════════════
        self.daily_winners = {}
        self.daily_winners_date = None
        
        # ═══════════════════════════════════════════════════════════════════
        # v3.7 RELAXED MOMENTUM FILTER
        # ═══════════════════════════════════════════════════════════════════
        self.min_green_today_pct = 0.005      # +0.5% green
        self.min_30min_gain_pct = 0.002       # +0.2% in last 30 min
        self.min_15min_gain_pct = 0.0005      # +0.05% in last 15 min
        self.max_from_high_pct = 0.003        # 0.3% below high
        
        # ═══════════════════════════════════════════════════════════════════
        # v3.7 TIME WINDOWS
        # ═══════════════════════════════════════════════════════════════════
        self.entry_start_time = dtime(9, 35)   # Start buying at 9:35 AM
        self.entry_cutoff_time = dtime(13, 0)  # Stop buying at 1:00 PM
        self.force_liquidation_time = dtime(15, 45)  # Sell everything at 3:45 PM
        
        # Morning dump settings
        self.morning_dump_enabled = True
        self.morning_dump_threshold = -0.003  # Dump if -0.3% or worse
        self.morning_dump_done = False
        
        # ═══════════════════════════════════════════════════════════════════
        # MARKET TREND CHECK
        # ═══════════════════════════════════════════════════════════════════
        self.check_market_trend = True
        self.market_trend_ticker = 'SPY'
        self.min_market_green_pct = -0.002  # SPY must be > -0.2%
        self.market_is_green = True
        
        # Position tracking
        self.profit_protection_enabled = True
        self.profit_trailing_drop = 0.004
        self.min_profit_to_exit = 0.002
        self.position_peaks = {}
        
        # Filters
        self.min_price = config.get('min_price', 15)
        self.max_price = config.get('max_price', 500)
        self.min_adx = 12
        self.trend_threshold_pct = 0.95
        self.rsi_min = 30
        self.rsi_max = 70
        self.min_volume_ratio = 0.15
        
        # State
        self.current_positions = {}
        self.entry_prices = {}
        
        # Stats
        self.signals_generated = 0
        self.signals_blocked_by_pdt = 0
        self.signals_blocked_by_momentum = 0
        self.signals_blocked_by_market = 0
        self.signals_blocked_by_time = 0
        self.current_scan_stats = {}
        self.cycle_count = 0
        
        pprint(f"")
        pprint(f"[INIT] SwingStrategyEngine v3.7 - PDT-SMART DAY TRADER")
        pprint(f"[INIT] ═══════════════════════════════════════════════════")
        pprint(f"[INIT] 🎯 GOAL: End EVERY day GREEN, never hold overnight")
        pprint(f"[INIT] 📊 PDT-AWARE: Max buys = day trades remaining")
        pprint(f"[INIT] 🌅 Morning dump: Sell overnight losers (FREE!)")
        pprint(f"[INIT] 🕐 Entry window: 9:35 AM - 1:00 PM only")
        pprint(f"[INIT] 🔴 EOD liquidation: 3:45 PM (sell everything)")
        pprint(f"[INIT] 💰 Profit preservation: ${self.profit_preservation_threshold:.2f}")
        pprint(f"[INIT] ═══════════════════════════════════════════════════")
        pprint(f"")
    
    def _check_new_day(self):
        """Reset daily trackers if it's a new day"""
        today = datetime.now(EST).date()
        
        if self.today_date != today:
            # New day - reset everything
            self.positions_bought_today = set()
            self.morning_dump_done = False
            self.today_date = today
            
            if self.daily_winners:
                pprint(f"[DAILY] New day - clearing {len(self.daily_winners)} winner blocks")
            self.daily_winners = {}
            self.daily_winners_date = today
            
            if self.profit_preservation_active:
                pprint(f"[DAILY] New day - resetting profit preservation")
            self.daily_realized_profit = 0.0
            self.profit_preservation_active = False
            self.profit_preservation_date = today
    
    def get_day_trades_remaining(self) -> int:
        """Get how many day trades we can still make today"""
        if self.pdt_tracker:
            try:
                status = self.pdt_tracker.get_status()
                used = status.get('day_trades_used', 0)
                remaining = self.max_day_trades - used
                return max(0, remaining)
            except:
                pass
        return self.max_day_trades  # Assume all available if no tracker
    
    def get_max_new_positions_today(self) -> int:
        """
        Calculate max positions we can buy TODAY.
        This equals day trades remaining because:
        - Every position bought today needs to be sold today (EOD liquidation)
        - Selling a same-day position uses 1 day trade
        - So max_buys = day_trades_remaining
        """
        return self.get_day_trades_remaining()
    
    def get_positions_bought_today_count(self) -> int:
        """How many positions have we already bought TODAY?"""
        self._check_new_day()
        return len(self.positions_bought_today)
    
    def can_buy_new_position(self) -> Tuple[bool, str]:
        """Check if we can buy a new position (PDT-aware)"""
        self._check_new_day()
        
        day_trades_remaining = self.get_day_trades_remaining()
        positions_bought_today = self.get_positions_bought_today_count()
        
        # We can only buy if we have day trades left to sell it at EOD
        if positions_bought_today >= day_trades_remaining:
            return False, f"PDT_LIMIT (bought {positions_bought_today}, only {day_trades_remaining} day trades left)"
        
        return True, f"OK ({positions_bought_today}/{day_trades_remaining} slots used)"
    
    def _check_market_trend(self) -> Tuple[bool, float]:
        """Check if SPY is green"""
        if not self.check_market_trend:
            return True, 0.0
        
        try:
            import yfinance as yf
            
            spy = yf.Ticker(self.market_trend_ticker)
            intraday = spy.history(period='1d', interval='5m')
            
            if intraday is None or len(intraday) < 2:
                return True, 0.0
            
            current = float(intraday['Close'].iloc[-1])
            open_price = float(intraday['Open'].iloc[0])
            change_pct = (current - open_price) / open_price
            
            self.market_is_green = change_pct >= self.min_market_green_pct
            return self.market_is_green, change_pct
            
        except:
            return True, 0.0
    
    def add_realized_profit(self, amount: float):
        self._check_new_day()
        self.daily_realized_profit += amount
        
        if not self.profit_preservation_active and self.daily_realized_profit >= self.profit_preservation_threshold:
            self.profit_preservation_active = True
            pprint(f"")
            pprint(f"  💰💰💰 PROFIT PRESERVATION ACTIVATED! 💰💰💰")
            pprint(f"  Daily profit: ${self.daily_realized_profit:.2f}")
            pprint(f"  NO NEW BUYS - protecting gains!")
            pprint(f"")
    
    def is_profit_preservation_active(self) -> bool:
        self._check_new_day()
        return self.profit_preservation_active
    
    def add_to_daily_winners(self, ticker: str, profit: float):
        self._check_new_day()
        self.daily_winners[ticker] = {'profit': profit}
    
    def is_daily_winner_blocked(self, ticker: str) -> Tuple[bool, str]:
        self._check_new_day()
        if ticker not in self.daily_winners:
            return False, ""
        return True, "WINNER_TODAY"
    
    def _load_loser_block_list(self):
        try:
            if os.path.exists(self.loser_block_file):
                with open(self.loser_block_file, 'r') as f:
                    self.loser_block_list = json.load(f)
                self._cleanup_expired_blocks()
        except:
            self.loser_block_list = {}
    
    def _save_loser_block_list(self):
        try:
            os.makedirs(os.path.dirname(self.loser_block_file), exist_ok=True)
            with open(self.loser_block_file, 'w') as f:
                json.dump(self.loser_block_list, f, indent=2)
        except:
            pass
    
    def _cleanup_expired_blocks(self):
        now = datetime.now(EST)
        expired = [t for t, info in self.loser_block_list.items() 
                   if now > datetime.fromisoformat(info.get('blocked_until', '2000-01-01'))]
        for ticker in expired:
            del self.loser_block_list[ticker]
        if expired:
            self._save_loser_block_list()
    
    def add_to_loser_block_list(self, ticker: str, loss_amount: float):
        now = datetime.now(EST)
        self.loser_block_list[ticker] = {
            'blocked_until': (now + timedelta(days=self.loser_block_days)).isoformat(),
            'loss_amount': loss_amount
        }
        self._save_loser_block_list()
    
    def is_blocked(self, ticker: str) -> Tuple[bool, str]:
        if ticker not in self.loser_block_list:
            return False, ""
        try:
            blocked_until = datetime.fromisoformat(self.loser_block_list[ticker].get('blocked_until', ''))
            if datetime.now(EST) > blocked_until:
                del self.loser_block_list[ticker]
                self._save_loser_block_list()
                return False, ""
            return True, "LOSER_BLOCKED"
        except:
            return False, ""
    
    def _check_momentum(self, ticker: str) -> Tuple[bool, str, Dict]:
        """Relaxed momentum check"""
        details = {}
        
        try:
            import yfinance as yf
            
            stock = yf.Ticker(ticker)
            intraday = stock.history(period='1d', interval='5m')
            
            if intraday is None or len(intraday) < 6:
                return False, "NO_DATA", details
            
            current = float(intraday['Close'].iloc[-1])
            today_open = float(intraday['Open'].iloc[0])
            today_high = float(intraday['High'].max())
            
            details['current_price'] = current
            details['today_change_pct'] = (current - today_open) / today_open
            
            # Check 1: Green today (+0.5%)
            if details['today_change_pct'] < self.min_green_today_pct:
                return False, f"RED ({details['today_change_pct']*100:+.2f}%)", details
            
            # Check 2: 30-min trend
            if len(intraday) >= 6:
                price_30m = float(intraday['Close'].iloc[-6])
                change_30m = (current - price_30m) / price_30m
                details['change_30min_pct'] = change_30m
                if change_30m < self.min_30min_gain_pct:
                    return False, f"30M_DOWN ({change_30m*100:+.2f}%)", details
            
            # Check 3: 15-min trend
            if len(intraday) >= 3:
                price_15m = float(intraday['Close'].iloc[-3])
                change_15m = (current - price_15m) / price_15m
                details['change_15min_pct'] = change_15m
                if change_15m < self.min_15min_gain_pct:
                    return False, f"15M_DOWN ({change_15m*100:+.2f}%)", details
            
            # Check 4: Not at peak
            if today_high > 0:
                below_high = (today_high - current) / today_high
                if below_high < self.max_from_high_pct:
                    return False, "AT_PEAK", details
            
            return True, "OK", details
            
        except Exception as e:
            return False, f"ERROR", details
    
    def set_sentiment_analyzer(self, analyzer):
        self.sentiment_analyzer = analyzer
    
    def update_positions(self, positions: Dict):
        self.current_positions = positions or {}
        
        # Clean up tracking for closed positions
        current_tickers = set(self.current_positions.keys())
        self.position_peaks = {k: v for k, v in self.position_peaks.items() if k in current_tickers}
    
    def record_entry(self, ticker: str, price: float):
        """Record a new position entry"""
        self._check_new_day()
        self.entry_prices[ticker] = {'price': price, 'time': datetime.now(EST)}
        self.position_peaks[ticker] = 0.0
        
        # Track that we bought this TODAY
        self.positions_bought_today.add(ticker)
        
        pprint(f"[PDT] 📝 Recorded buy: {ticker}")
        pprint(f"[PDT]    Positions bought today: {len(self.positions_bought_today)}")
        pprint(f"[PDT]    Day trades remaining: {self.get_day_trades_remaining()}")
    
    def record_exit(self, ticker: str, pnl: float = 0):
        """Record a position exit"""
        self.entry_prices.pop(ticker, None)
        self.position_peaks.pop(ticker, None)
        
        # Note: We don't remove from positions_bought_today because
        # we need to track day trades used. The PDT tracker handles the actual count.
        
        self.add_realized_profit(pnl)
        
        if pnl < 0:
            self.add_to_loser_block_list(ticker, pnl)
        elif pnl > 0:
            self.add_to_daily_winners(ticker, pnl)
    
    def is_position_from_today(self, ticker: str) -> bool:
        """Check if position was bought today (uses day trade to sell)"""
        self._check_new_day()
        return ticker in self.positions_bought_today
    
    def generate_signals(self, universe: List[str]) -> List[Dict]:
        et = datetime.now(EST)
        self.cycle_count += 1
        self._check_new_day()
        self._cleanup_expired_blocks()
        
        # Get PDT status
        day_trades_remaining = self.get_day_trades_remaining()
        positions_bought_today = self.get_positions_bought_today_count()
        can_buy, buy_status = self.can_buy_new_position()
        
        # Check market
        market_ok, market_pct = self._check_market_trend()
        market_icon = "🟢" if market_ok else "🔴"
        
        # Count position types
        overnight_positions = [t for t in self.current_positions.keys() if not self.is_position_from_today(t)]
        today_positions = [t for t in self.current_positions.keys() if self.is_position_from_today(t)]
        
        pprint("")
        pprint("=" * 70)
        pprint(f"  CYCLE {self.cycle_count} | {et.strftime('%H:%M:%S')} ET | v3.7 PDT-SMART")
        pprint(f"  {market_icon} SPY: {market_pct*100:+.2f}% | 💰 P&L: ${self.daily_realized_profit:+.2f}")
        pprint(f"  📊 Day Trades: {day_trades_remaining}/3 remaining")
        pprint(f"  📦 Positions: {len(overnight_positions)} overnight, {len(today_positions)} today")
        pprint(f"  🎯 Can buy: {can_buy} ({buy_status})")
        pprint("=" * 70)
        
        all_signals = []
        
        if self.reporter:
            try:
                self.reporter.log_scan_start(len(universe), self.min_confidence)
            except:
                pass
        
        # ═══════════════════════════════════════════════════════════════════
        # MORNING DUMP (9:30-9:45): Sell overnight losers - FREE, no day trade!
        # ═══════════════════════════════════════════════════════════════════
        if not self.morning_dump_done and dtime(9, 30) <= et.time() < dtime(9, 45):
            if overnight_positions:
                pprint("")
                pprint("  🌅 MORNING DUMP - Checking overnight positions...")
                pprint("     (Selling overnight positions = FREE, no day trade used!)")
                morning_exits = self._check_morning_dump(overnight_positions)
                all_signals.extend(morning_exits)
            self.morning_dump_done = True
        
        # ═══════════════════════════════════════════════════════════════════
        # EOD LIQUIDATION (3:45 PM): Sell EVERYTHING
        # ═══════════════════════════════════════════════════════════════════
        if et.time() >= self.force_liquidation_time:
            pprint("")
            pprint("  🔴 EOD LIQUIDATION - 3:45 PM - Selling ALL positions!")
            liquidation_exits = self._force_liquidate_all()
            all_signals.extend(liquidation_exits)
            return all_signals
        
        # ═══════════════════════════════════════════════════════════════════
        # REGULAR EXITS
        # ═══════════════════════════════════════════════════════════════════
        pprint("")
        pprint("  [1/2] Checking exits (stop loss, take profit)...")
        exit_signals = self._generate_exit_signals()
        all_signals.extend(exit_signals)
        
        # ═══════════════════════════════════════════════════════════════════
        # ENTRIES (with all checks)
        # ═══════════════════════════════════════════════════════════════════
        entries_blocked = False
        block_reason = ""
        
        if self.profit_preservation_active:
            entries_blocked = True
            block_reason = "PROFIT_PRESERVATION"
        elif et.time() < self.entry_start_time:
            entries_blocked = True
            block_reason = "TOO_EARLY (wait for 9:35)"
        elif et.time() >= self.entry_cutoff_time:
            entries_blocked = True
            block_reason = "TOO_LATE (cutoff 1:00 PM)"
            self.signals_blocked_by_time += 1
        elif not can_buy:
            entries_blocked = True
            block_reason = buy_status
            self.signals_blocked_by_pdt += 1
        elif not market_ok:
            entries_blocked = True
            block_reason = f"MARKET_RED (SPY {market_pct*100:+.2f}%)"
            self.signals_blocked_by_market += 1
        
        pprint("")
        if entries_blocked:
            pprint(f"  [2/2] ⛔ ENTRIES BLOCKED: {block_reason}")
        else:
            pprint(f"  [2/2] Scanning for entries...")
            pprint(f"        Slots available: {day_trades_remaining - positions_bought_today}")
            entry_signals = self._generate_entry_signals(universe, day_trades_remaining - positions_bought_today)
            all_signals.extend(entry_signals)
        
        pprint("=" * 70)
        return all_signals
    
    def _check_morning_dump(self, overnight_tickers: List[str]) -> List[Dict]:
        """Dump overnight positions that are red"""
        exit_signals = []
        
        for ticker in overnight_tickers:
            pos = self.current_positions.get(ticker)
            if not pos:
                continue
            
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = int(pos.get('quantity', 0))
            
            if entry_price <= 0:
                continue
            
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollars = (current_price - entry_price) * quantity
            
            if pnl_pct <= self.morning_dump_threshold:
                pprint(f"     🔴 {ticker}: {pnl_pct*100:+.2f}% (${pnl_dollars:+.2f}) >>> DUMP!")
                exit_signals.append({
                    'ticker': ticker,
                    'is_exit': True,
                    'reason': f"MORNING_DUMP (overnight loss)",
                    'price': current_price,
                    'pnl_pct': pnl_pct,
                    'pnl_dollars': pnl_dollars,
                    'is_overnight': True  # Flag: no day trade used!
                })
            else:
                icon = "🟢" if pnl_pct >= 0 else "🟡"
                pprint(f"     {icon} {ticker}: {pnl_pct*100:+.2f}% - keeping")
        
        return exit_signals
    
    def _force_liquidate_all(self) -> List[Dict]:
        """Force sell everything at EOD"""
        exit_signals = []
        
        if not self.current_positions:
            pprint("     No positions to liquidate")
            return exit_signals
        
        for ticker, pos in self.current_positions.items():
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = int(pos.get('quantity', 0))
            
            if entry_price <= 0:
                continue
            
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollars = (current_price - entry_price) * quantity
            is_overnight = not self.is_position_from_today(ticker)
            
            icon = "🟢" if pnl_pct >= 0 else "🔴"
            dt_note = "(FREE)" if is_overnight else "(uses day trade)"
            
            pprint(f"     {icon} {ticker}: {pnl_pct*100:+.2f}% (${pnl_dollars:+.2f}) >>> LIQUIDATE {dt_note}")
            
            exit_signals.append({
                'ticker': ticker,
                'is_exit': True,
                'reason': "EOD_LIQUIDATION",
                'price': current_price,
                'pnl_pct': pnl_pct,
                'pnl_dollars': pnl_dollars,
                'is_overnight': is_overnight
            })
        
        return exit_signals
    
    def _generate_exit_signals(self) -> List[Dict]:
        exit_signals = []
        
        if not self.current_positions:
            pprint("        No positions")
            return exit_signals
        
        for ticker, pos in self.current_positions.items():
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = int(pos.get('quantity', 0))
            
            if entry_price <= 0:
                continue
            
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollars = (current_price - entry_price) * quantity
            is_overnight = not self.is_position_from_today(ticker)
            
            exit_signal = None
            reason = None
            
            # Take profit
            if pnl_pct >= self.take_profit_pct:
                exit_signal = True
                reason = f"TAKE_PROFIT ({pnl_pct*100:.2f}%)"
            
            # Stop loss
            elif pnl_pct <= -self.stop_loss_pct:
                exit_signal = True
                reason = f"STOP_LOSS ({pnl_pct*100:.2f}%)"
            
            # Catastrophic stop
            elif pnl_pct <= -0.05:
                exit_signal = True
                reason = f"CATASTROPHIC ({pnl_pct*100:.2f}%)"
            
            # Trailing profit
            elif self.profit_protection_enabled and pnl_pct > 0:
                peak = self.position_peaks.get(ticker, 0)
                if pnl_pct > peak:
                    self.position_peaks[ticker] = pnl_pct
                elif peak - pnl_pct >= self.profit_trailing_drop and pnl_pct >= self.min_profit_to_exit:
                    exit_signal = True
                    reason = f"TRAILING ({peak*100:.2f}% → {pnl_pct*100:.2f}%)"
            
            icon = "🟢" if pnl_pct >= 0 else "🔴"
            otype = "overnight" if is_overnight else "today"
            pprint(f"        {icon} {ticker} ({otype}): {pnl_pct*100:+.2f}% (${pnl_dollars:+.2f})")
            
            if self.reporter:
                try:
                    self.reporter.log_exit_evaluation({
                        'ticker': ticker, 'pnl_pct': pnl_pct,
                        'decision': 'EXIT' if exit_signal else 'HOLD',
                        'reason': reason or "Within thresholds"
                    })
                except:
                    pass
            
            if exit_signal:
                pprint(f"           >>> EXIT: {reason}")
                exit_signals.append({
                    'ticker': ticker, 'is_exit': True, 'reason': reason,
                    'price': current_price, 'pnl_pct': pnl_pct, 'pnl_dollars': pnl_dollars,
                    'is_overnight': is_overnight
                })
        
        return exit_signals
    
    def _generate_entry_signals(self, universe: List[str], max_entries: int) -> List[Dict]:
        if max_entries <= 0:
            pprint(f"        No entry slots available")
            return []
        
        entry_signals = []
        scan_limit = min(len(universe), 100)
        
        stats = {
            'total_scanned': 0, 'data_errors': 0, 'filtered': 0,
            'momentum_rejected': 0, 'signals_found': 0
        }
        
        for i, ticker in enumerate(universe[:scan_limit]):
            stats['total_scanned'] += 1
            
            if len(entry_signals) >= max_entries:
                pprint(f"        Reached max entries ({max_entries})")
                break
            
            if (i + 1) % 25 == 0:
                pprint(f"        ... {i+1}/{scan_limit} | signals: {stats['signals_found']}")
            
            # Block checks
            if self.is_blocked(ticker)[0] or self.is_daily_winner_blocked(ticker)[0]:
                stats['filtered'] += 1
                continue
            
            try:
                result = self._evaluate_ticker(ticker)
                
                if result is None:
                    stats['data_errors'] += 1
                    continue
                
                if not result.get('signal'):
                    stats['filtered'] += 1
                    continue
                
                # Momentum check
                momentum_ok, momentum_reason, momentum_details = self._check_momentum(ticker)
                if not momentum_ok:
                    stats['momentum_rejected'] += 1
                    self.signals_blocked_by_momentum += 1
                    continue
                
                confidence = result.get('confidence', 0)
                if confidence < self.min_confidence:
                    stats['filtered'] += 1
                    continue
                
                # Signal passed!
                stats['signals_found'] += 1
                self.signals_generated += 1
                
                price = result.get('price', 0)
                today_chg = momentum_details.get('today_change_pct', 0) * 100
                
                pprint(f"")
                pprint(f"        ✅ SIGNAL: {ticker} @ ${price:.2f} | {confidence:.0%} | +{today_chg:.2f}%")
                
                if self.reporter:
                    try:
                        self.reporter.log_signal({'ticker': ticker, 'price': price, 'confidence': confidence})
                    except:
                        pass
                
                entry_signals.append({
                    'ticker': ticker,
                    'is_exit': False,
                    'confidence': confidence,
                    'price': price,
                    'strategy': 'swing',
                    'momentum_details': momentum_details
                })
                
                time.sleep(0.05)
                
            except:
                stats['data_errors'] += 1
                continue
        
        pprint(f"")
        pprint(f"        ╔═══════════════════════════════════╗")
        pprint(f"        ║  SCAN RESULTS v3.7                ║")
        pprint(f"        ╠═══════════════════════════════════╣")
        pprint(f"        ║  Scanned:          {stats['total_scanned']:>6}         ║")
        pprint(f"        ║  Momentum Reject:  {stats['momentum_rejected']:>6}         ║")
        pprint(f"        ╠═══════════════════════════════════╣")
        pprint(f"        ║  ✅ SIGNALS:       {stats['signals_found']:>6}         ║")
        pprint(f"        ╚═══════════════════════════════════╝")
        
        if self.reporter:
            try:
                self.reporter.log_scan_complete(stats)
            except:
                pass
        
        self.current_scan_stats = stats
        return entry_signals
    
    def _evaluate_ticker(self, ticker: str) -> Optional[Dict]:
        try:
            df = None
            
            if self.data_manager:
                try:
                    df = self.data_manager.fetch_historical_data(ticker, period='1mo', interval='1d')
                except:
                    pass
            
            if df is None or len(df) < 15:
                try:
                    import yfinance as yf
                    df = yf.download(ticker, period='1mo', progress=False, auto_adjust=True)
                except:
                    return None
            
            if df is None or len(df) < 15 or 'Close' not in df.columns:
                return None
            
            price = float(df['Close'].iloc[-1])
            
            if price <= 0 or pd.isna(price) or price < self.min_price or price > self.max_price:
                return None
            
            # Calculate indicators
            sma20 = df['Close'].rolling(20).mean().iloc[-1]
            
            delta = df['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain.iloc[-1] / (loss.iloc[-1] + 0.0001)))
            
            # Simple ADX approximation
            high, low, close = df['High'], df['Low'], df['Close']
            tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            adx = min(50, max(10, 100 * atr / price))  # Simplified
            
            # Volume
            if 'Volume' in df.columns:
                vol_ratio = df['Volume'].iloc[-1] / (df['Volume'].rolling(20).mean().iloc[-1] + 1)
            else:
                vol_ratio = 1.0
            
            # Filters
            if adx < self.min_adx or price < sma20 * self.trend_threshold_pct:
                return {'signal': False}
            if rsi < self.rsi_min or rsi > self.rsi_max:
                return {'signal': False}
            if vol_ratio < self.min_volume_ratio:
                return {'signal': False}
            
            # Calculate confidence
            confidence = 0.82
            if adx > 25: confidence += 0.03
            if 45 <= rsi <= 55: confidence += 0.02
            if vol_ratio > 1.0: confidence += 0.02
            confidence = min(0.95, confidence)
            
            return {'signal': True, 'price': price, 'confidence': confidence}
            
        except:
            return None
    
    def get_stats(self) -> Dict:
        return {
            'signals_generated': self.signals_generated,
            'signals_blocked_by_pdt': self.signals_blocked_by_pdt,
            'signals_blocked_by_momentum': self.signals_blocked_by_momentum,
            'signals_blocked_by_market': self.signals_blocked_by_market,
            'signals_blocked_by_time': self.signals_blocked_by_time,
            'positions_bought_today': list(self.positions_bought_today),
            'day_trades_remaining': self.get_day_trades_remaining(),
            'daily_realized_profit': self.daily_realized_profit,
            'last_scan_stats': self.current_scan_stats
        }
