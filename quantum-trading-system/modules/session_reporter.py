"""
SESSION REPORTER v5.1 - ACTUALLY CAPTURES EVERYTHING
═══════════════════════════════════════════════════════════════════════════════

v5.1 FIXES:
- Added log_scan_complete() method to capture scan statistics
- Fixed universe_stats to properly update from scan results
- Added detailed scan log with every ticker result
- Cycle log now shows actual signal counts
- All data flows from swing_strategy -> reporter -> report file

═══════════════════════════════════════════════════════════════════════════════
"""
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5))

def get_eastern_time() -> datetime:
    return datetime.now(EST)

def format_et(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EST)
    return dt.astimezone(EST).strftime('%H:%M:%S')


class UltraVerboseReporter:
    """Captures every detail of a trading session - v5.1 FIXED"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.start_time = None
        self.end_time = None
        
        # Initial/Final state
        self.initial_state = {}
        self.final_state = {}
        
        # ═══════════════════════════════════════════════════════════════
        # COMPREHENSIVE TRACKING
        # ═══════════════════════════════════════════════════════════════
        
        # Scanning logs - EVERY ticker evaluation
        self.scan_log = []
        
        # Scan statistics per cycle
        self.scan_stats_history = []
        
        # Signal logs
        self.signals_generated = []
        self.signals_rejected = []
        
        # Trade logs
        self.trades = []
        self.trade_attempts = []
        
        # Position tracking
        self.position_snapshots = []
        
        # Market condition logs
        self.market_conditions = []
        
        # PDT tracking
        self.pdt_events = []
        
        # Exit/Entry decision logs
        self.exit_evaluations = []
        self.entry_evaluations = []
        
        # API call logs
        self.api_calls = []
        
        # Error/Warning logs
        self.errors = []
        self.warnings = []
        
        # Cycle logs
        self.cycle_logs = []
        
        # Strategy performance
        self.strategy_signals = defaultdict(list)
        
        # Sentiment logs
        self.sentiment_logs = []
        
        # Universe tracking - FIXED: Updated by log_scan_complete
        self.universe_stats = {
            'total_scanned': 0,
            'data_errors': 0,
            'passed_price_filter': 0,
            'passed_volume_filter': 0,
            'passed_trend_filter': 0,
            'passed_adx_filter': 0,
            'passed_rsi_filter': 0,
            'passed_strategy_filter': 0,
            'generated_signal': 0,
            'above_threshold': 0,
            'news_blocked': 0,
            'news_boosted': 0
        }
        
        # Timing metrics
        self.cycle_times = []
        
        # Current cycle data
        self.current_cycle_signals = 0
        
        logger.info(f"UltraVerboseReporter v5.1 initialized | Session: {self.session_id}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # SESSION LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    
    def start_session(self, initial_state: Dict):
        """Start a new trading session"""
        self.start_time = get_eastern_time()
        self.initial_state = initial_state.copy()
        self.log_event('SESSION_START', {
            'session_id': self.session_id,
            'initial_value': initial_state.get('portfolio_value'),
            'positions': list(initial_state.get('positions', {}).keys()),
            'cash': initial_state.get('cash')
        })
    
    def end_session(self, final_state: Dict, metrics: Dict):
        """End the trading session"""
        self.end_time = get_eastern_time()
        self.final_state = final_state.copy()
        self.final_state['metrics'] = metrics
        self.log_event('SESSION_END', {
            'final_value': final_state.get('portfolio_value'),
            'daily_pnl': final_state.get('daily_pnl'),
            'metrics': metrics
        })
    
    # ═══════════════════════════════════════════════════════════════════════
    # SCANNING LOGS - FIXED!
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_scan_start(self, universe_size: int, confidence_threshold: float = 0.85):
        """Log the start of a scanning cycle"""
        self.current_cycle_signals = 0
        self.log_event('SCAN_START', {
            'universe_size': universe_size,
            'confidence_threshold': confidence_threshold,
            'time': format_et(get_eastern_time())
        })
    
    def log_scan_complete(self, stats: Dict):
        """
        Log scan completion with full statistics - THIS WAS MISSING!
        
        stats should contain:
        - total_scanned, data_errors, price_filtered, adx_filtered
        - trend_filtered, rsi_filtered, volume_filtered
        - strategy_filtered, confidence_filtered
        - news_blocked, news_boosted, signals_found
        """
        # Update universe stats
        self.universe_stats['total_scanned'] += stats.get('total_scanned', 0)
        self.universe_stats['data_errors'] += stats.get('data_errors', 0)
        
        # Calculate passed filters (inverted from filtered counts)
        total = stats.get('total_scanned', 0)
        self.universe_stats['passed_price_filter'] += total - stats.get('data_errors', 0) - stats.get('price_filtered', 0)
        self.universe_stats['passed_adx_filter'] += total - stats.get('data_errors', 0) - stats.get('price_filtered', 0) - stats.get('adx_filtered', 0)
        self.universe_stats['passed_trend_filter'] += stats.get('passed_all_filters', 0) + stats.get('signals_found', 0)
        self.universe_stats['passed_volume_filter'] += total - stats.get('volume_filtered', 0) - stats.get('data_errors', 0)
        self.universe_stats['generated_signal'] += stats.get('signals_found', 0)
        self.universe_stats['above_threshold'] += stats.get('signals_found', 0)
        self.universe_stats['news_blocked'] += stats.get('news_blocked', 0)
        self.universe_stats['news_boosted'] += stats.get('news_boosted', 0)
        
        # Store stats for this scan
        scan_record = {
            'time': format_et(get_eastern_time()),
            **stats
        }
        self.scan_stats_history.append(scan_record)
        self.current_cycle_signals = stats.get('signals_found', 0)
        
        self.log_event('SCAN_COMPLETE', scan_record)
    
    def log_ticker_scan(self, ticker: str, scan_result: Dict):
        """Log detailed scan results for a single ticker"""
        entry = {
            'time': format_et(get_eastern_time()),
            'ticker': ticker,
            **scan_result
        }
        self.scan_log.append(entry)
        
        # Also log as signal if it's a signal
        if scan_result.get('result') == 'SIGNAL':
            self.signals_generated.append(entry)
    
    def log_quick_filter(self, ticker: str, filter_name: str, passed: bool, 
                         value: Any = None, threshold: Any = None, reason: str = None):
        """Log a quick filter result"""
        self.scan_log.append({
            'time': format_et(get_eastern_time()),
            'ticker': ticker,
            'type': 'quick_filter',
            'filter': filter_name,
            'passed': passed,
            'value': value,
            'threshold': threshold,
            'reason': reason
        })
    
    # ═══════════════════════════════════════════════════════════════════════
    # CYCLE LOGGING - FIXED!
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_cycle(self, cycle_data: Dict, scan_summary: Dict = None):
        """Log a complete cycle with all data"""
        cycle_entry = {
            'time': format_et(get_eastern_time()),
            'cycle': cycle_data.get('cycle', 0),
            'portfolio_value': cycle_data.get('portfolio_value', 0),
            'daily_pnl': cycle_data.get('daily_pnl', 0),
            'position_count': cycle_data.get('positions_count', 0),
            'regime': cycle_data.get('regime', 'UNKNOWN'),
            'signals_count': self.current_cycle_signals,  # Use actual count!
            'status': cycle_data.get('status', '')
        }
        
        if scan_summary:
            cycle_entry['scan_summary'] = scan_summary
        
        self.cycle_logs.append(cycle_entry)
    
    # ═══════════════════════════════════════════════════════════════════════
    # TRADE LOGGING
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_trade(self, trade_data: Dict):
        """Log an executed trade"""
        entry = {
            'time': format_et(get_eastern_time()),
            **trade_data
        }
        self.trades.append(entry)
        self.log_event('TRADE', entry)
    
    def log_trade_attempt(self, attempt_data: Dict):
        """Log a trade attempt (including failures)"""
        entry = {
            'time': format_et(get_eastern_time()),
            **attempt_data
        }
        self.trade_attempts.append(entry)
    
    # ═══════════════════════════════════════════════════════════════════════
    # EXIT/ENTRY EVALUATION LOGGING
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_exit_evaluation(self, eval_data: Dict):
        """Log an exit evaluation"""
        entry = {
            'time': format_et(get_eastern_time()),
            **eval_data
        }
        self.exit_evaluations.append(entry)
    
    def log_entry_evaluation(self, eval_data: Dict):
        """Log an entry evaluation"""
        entry = {
            'time': format_et(get_eastern_time()),
            **eval_data
        }
        self.entry_evaluations.append(entry)
    
    # ═══════════════════════════════════════════════════════════════════════
    # MARKET CONDITIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_market_conditions(self, conditions: Dict):
        """Log market conditions"""
        entry = {
            'time': format_et(get_eastern_time()),
            **conditions
        }
        self.market_conditions.append(entry)
    
    # ═══════════════════════════════════════════════════════════════════════
    # SENTIMENT LOGGING
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_sentiment(self, sentiment_data: Dict):
        """Log sentiment analysis result"""
        entry = {
            'time': format_et(get_eastern_time()),
            **sentiment_data
        }
        self.sentiment_logs.append(entry)
    
    # ═══════════════════════════════════════════════════════════════════════
    # ERROR/WARNING LOGGING
    # ═══════════════════════════════════════════════════════════════════════
    
    def log_error(self, context: str, error: str):
        """Log an error"""
        self.errors.append({
            'time': format_et(get_eastern_time()),
            'context': context,
            'error': error
        })
    
    def log_warning(self, context: str, message: str):
        """Log a warning"""
        self.warnings.append({
            'time': format_et(get_eastern_time()),
            'context': context,
            'message': message
        })
    
    def log_event(self, event_type: str, data: Dict):
        """Generic event logging"""
        logger.debug(f"[{event_type}] {data}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # REPORT GENERATION - FIXED!
    # ═══════════════════════════════════════════════════════════════════════
    
    def generate_report(self) -> str:
        """Generate comprehensive session report"""
        report = []
        
        # Header
        report.append("# QUANTUM TRADING SYSTEM - ULTRA-VERBOSE SESSION REPORT")
        report.append(f"**Session ID:** {self.session_id}")
        
        et_now = get_eastern_time()
        local_now = datetime.now()
        report.append(f"**Generated:** {et_now.strftime('%Y-%m-%d %H:%M:%S')} ET (Local: {local_now.strftime('%H:%M:%S')})")
        report.append("**All timestamps in Eastern Time (ET)**")
        report.append("")
        report.append("---")
        report.append("")
        
        # Executive Summary
        report.append("## EXECUTIVE SUMMARY")
        report.append("")
        
        runtime = (self.end_time - self.start_time) if self.end_time and self.start_time else timedelta(0)
        initial_value = self.initial_state.get('portfolio_value', 0)
        final_value = self.final_state.get('portfolio_value', initial_value)
        session_pnl = final_value - initial_value
        session_pnl_pct = (session_pnl / initial_value * 100) if initial_value else 0
        
        metrics = self.final_state.get('metrics', {})
        total_trades = metrics.get('trades', len(self.trades))
        wins = metrics.get('wins', 0)
        losses = metrics.get('losses', 0)
        win_rate = (wins / total_trades * 100) if total_trades else 0
        
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        report.append(f"| Runtime | {runtime} |")
        report.append(f"| Initial Value | ${initial_value:,.2f} |")
        report.append(f"| Final Value | ${final_value:,.2f} |")
        report.append(f"| Session P&L | ${session_pnl:+,.2f} ({session_pnl_pct:+.2f}%) |")
        report.append(f"| Trades | {total_trades} |")
        report.append(f"| Won / Lost | {wins} / {losses} ({win_rate:.1f}%) |")
        report.append(f"| Signals Generated | {self.universe_stats.get('generated_signal', 0)} |")
        report.append(f"| News Blocked | {self.universe_stats.get('news_blocked', 0)} |")
        report.append(f"| News Boosted | {self.universe_stats.get('news_boosted', 0)} |")
        report.append(f"| Tickers Scanned | {self.universe_stats.get('total_scanned', 0)} |")
        report.append(f"| Errors | {len(self.errors)} |")
        report.append(f"| Warnings | {len(self.warnings)} |")
        report.append("")
        
        # Scan Statistics Per Cycle
        report.append("## SCAN STATISTICS BY CYCLE")
        report.append("")
        if self.scan_stats_history:
            report.append("| Cycle | Time | Scanned | Errors | Price | ADX | Trend | RSI | Volume | Strategy | Conf | News Block | Signals |")
            report.append("|-------|------|---------|--------|-------|-----|-------|-----|--------|----------|------|------------|---------|")
            for i, stats in enumerate(self.scan_stats_history):
                report.append(f"| {i+1} | {stats.get('time', '')} | {stats.get('total_scanned', 0)} | {stats.get('data_errors', 0)} | {stats.get('price_filtered', 0)} | {stats.get('adx_filtered', 0)} | {stats.get('trend_filtered', 0)} | {stats.get('rsi_filtered', 0)} | {stats.get('volume_filtered', 0)} | {stats.get('strategy_filtered', 0)} | {stats.get('confidence_filtered', 0)} | {stats.get('news_blocked', 0)} | {stats.get('signals_found', 0)} |")
        else:
            report.append("*No scan statistics captured - check swing_strategy reporter integration*")
        report.append("")
        
        # Cumulative Filter Funnel
        report.append("## CUMULATIVE FILTER FUNNEL")
        report.append("")
        total = self.universe_stats.get('total_scanned', 0)
        if total > 0:
            report.append("| Stage | Count | % of Total |")
            report.append("|-------|-------|------------|")
            report.append(f"| Total Scanned | {total} | 100% |")
            report.append(f"| Data Errors | {self.universe_stats.get('data_errors', 0)} | {self.universe_stats.get('data_errors', 0)/total*100:.1f}% |")
            report.append(f"| Passed All Filters | {self.universe_stats.get('generated_signal', 0)} | {self.universe_stats.get('generated_signal', 0)/total*100:.1f}% |")
            report.append(f"| Generated Signal | {self.universe_stats.get('generated_signal', 0)} | {self.universe_stats.get('generated_signal', 0)/total*100:.1f}% |")
        else:
            report.append("*No tickers scanned*")
        report.append("")
        
        # Trades Executed
        report.append("## TRADES EXECUTED")
        report.append("")
        if self.trades:
            report.append("| Time | Ticker | Action | Qty | Price | P&L | Strategy |")
            report.append("|------|--------|--------|-----|-------|-----|----------|")
            for trade in self.trades:
                time_str = trade.get('time', '')
                ticker = trade.get('ticker', '')
                action = trade.get('action', '')
                qty = trade.get('quantity', 0)
                price = trade.get('price', 0)
                pnl = trade.get('pnl', 0)
                strategy = trade.get('strategy', '')
                report.append(f"| {time_str} | {ticker} | {action} | {qty} | ${price:.2f} | ${pnl:+.2f} | {strategy} |")
        else:
            report.append("*No trades executed*")
        report.append("")
        
        # Signals Generated
        report.append("## SIGNALS GENERATED")
        report.append("")
        if self.signals_generated:
            report.append("| Time | Ticker | Result | Confidence | Details |")
            report.append("|------|--------|--------|------------|---------|")
            for sig in self.signals_generated[-50:]:
                time_str = sig.get('time', '')
                ticker = sig.get('ticker', '')
                result = sig.get('result', '')
                details = sig.get('details', {})
                conf = details.get('final_confidence', details.get('confidence', 0))
                strategies = details.get('strategies', [])
                report.append(f"| {time_str} | {ticker} | {result} | {conf:.0%} | {strategies} |")
        else:
            report.append("*No signals generated*")
        report.append("")
        
        # Detailed Scan Log (last 100)
        report.append("## DETAILED SCAN LOG (Last 100 entries)")
        report.append("")
        report.append("```")
        if self.scan_log:
            for entry in self.scan_log[-100:]:
                ticker = entry.get('ticker', '')
                result = entry.get('result', entry.get('filter', ''))
                reason = entry.get('reason', '')
                report.append(f"{entry.get('time', '')} | {ticker} | {result} | {reason}")
        report.append("```")
        report.append("")
        
        # Exit Evaluations
        report.append("## EXIT EVALUATIONS")
        report.append("")
        if self.exit_evaluations:
            report.append("| Time | Ticker | Entry | Current | P&L% | Decision | Reason |")
            report.append("|------|--------|-------|---------|------|----------|--------|")
            for ev in self.exit_evaluations[-30:]:
                report.append(f"| {ev.get('time', '')} | {ev.get('ticker', '')} | ${ev.get('entry_price', 0):.2f} | ${ev.get('current_price', 0):.2f} | {ev.get('pnl_pct', 0)*100:.2f}% | {ev.get('decision', '')} | {ev.get('reason', '')} |")
        else:
            report.append("*No exit evaluations logged*")
        report.append("")
        
        # Sentiment Analysis
        report.append("## SENTIMENT ANALYSIS LOG")
        report.append("")
        if self.sentiment_logs:
            report.append("| Time | Ticker | Base Conf | Adjusted | Trade? | Reason |")
            report.append("|------|--------|-----------|----------|--------|--------|")
            for sent in self.sentiment_logs[-30:]:
                report.append(f"| {sent.get('time', '')} | {sent.get('ticker', '')} | {sent.get('base_confidence', 0):.0%} | {sent.get('adjusted_confidence', 0):.0%} | {sent.get('should_trade', '')} | {sent.get('reason', '')} |")
        else:
            report.append("*No sentiment analysis logged*")
        report.append("")
        
        # Errors
        report.append("## ERRORS")
        report.append("")
        if self.errors:
            report.append("```")
            for err in self.errors:
                report.append(f"{err.get('time', '')} | {err.get('context', '')} | {err.get('error', '')}")
            report.append("```")
        else:
            report.append("*No errors*")
        report.append("")
        
        # Warnings
        report.append("## WARNINGS")
        report.append("")
        if self.warnings:
            report.append("```")
            for warn in self.warnings:
                report.append(f"{warn.get('time', '')} | {warn.get('context', '')} | {warn.get('message', '')}")
            report.append("```")
        else:
            report.append("*No warnings*")
        report.append("")
        
        # Cycle Log
        report.append("## CYCLE LOG")
        report.append("")
        if self.cycle_logs:
            report.append("| Cycle | Time | Positions | Value | Day P&L | Signals | Regime |")
            report.append("|-------|------|-----------|-------|---------|---------|--------|")
            for cycle in self.cycle_logs[-50:]:
                report.append(f"| {cycle.get('cycle', 0)} | {cycle.get('time', '')} | {cycle.get('position_count', 0)} | ${cycle.get('portfolio_value', 0):.2f} | ${cycle.get('daily_pnl', 0):+.2f} | {cycle.get('signals_count', 0)} | {cycle.get('regime', '')} |")
        else:
            report.append("*No cycle logs*")
        report.append("")
        
        # Configuration
        report.append("## CONFIGURATION")
        report.append("")
        report.append("```json")
        safe_config = self.config.copy()
        for key in ['alpaca_secret', 'x_api_secret', 'x_bearer_token']:
            if key in safe_config:
                safe_config[key] = '***REDACTED***'
        for key in ['alpaca_key', 'newsapi_key', 'x_api_key']:
            if key in safe_config and safe_config[key]:
                safe_config[key] = safe_config[key][:10] + '...'
        report.append(json.dumps(safe_config, indent=2))
        report.append("```")
        report.append("")
        
        # Initial/Final State
        report.append("## INITIAL STATE")
        report.append("```json")
        report.append(json.dumps(self.initial_state, indent=2, default=str))
        report.append("```")
        report.append("")
        
        report.append("## FINAL STATE")
        report.append("```json")
        report.append(json.dumps(self.final_state, indent=2, default=str))
        report.append("```")
        report.append("")
        
        report.append("---")
        report.append("*UltraVerboseReporter v5.1 - Full transparency for maximum fine-tuning*")
        
        # Save report
        report_text = '\n'.join(report)
        self._save_report(report_text)
        
        return report_text
    
    def _save_report(self, report_text: str):
        """Save report to file"""
        try:
            os.makedirs('reports', exist_ok=True)
            filename = f"reports/session_{self.session_id}.md"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report_text)
            logger.info(f"Report saved: {filename}")
            print(f"[REPORT] Saved: {filename}", flush=True)
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
            try:
                import re
                clean_text = re.sub(r'[^\x00-\x7F]+', '', report_text)
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(clean_text)
                logger.info(f"Report saved (ASCII only): {filename}")
            except Exception as e2:
                logger.error(f"Fallback save also failed: {e2}")


def init_reporter(config: Dict) -> UltraVerboseReporter:
    """Initialize the reporter"""
    return UltraVerboseReporter(config)
