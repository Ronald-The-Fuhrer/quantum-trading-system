"""
QUANTUM TRADING SYSTEM v10.6 PATCHER
Run from C:\\quantum-trading-system:  python patch_v10_6.py

FIX 1: Ghost position cleanup when Alpaca already sold externally
FIX 2: Deduplicate exit signals (morning dump + stop loss fired twice for CF)
"""
import os
import sys


def main():
    print("=" * 60)
    print("  QUANTUM TRADING SYSTEM v10.6 PATCHER")
    print("  Fixes: Ghost cleanup + duplicate exit dedup")
    print("=" * 60)
    print()

    if not os.path.exists('main.py'):
        print("ERROR: main.py not found! Run from C:\\quantum-trading-system")
        sys.exit(1)

    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    original = content
    changes = 0

    # Backup
    backup = 'main.py.bak_v10_6'
    if not os.path.exists(backup):
        with open(backup, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  Backup saved: {backup}")

    # ══════════════════════════════════════════════════════════════
    # FIX 1: After SELL FAILED, check if position is gone at Alpaca
    # ══════════════════════════════════════════════════════════════
    print()
    print("FIX 1: Ghost position cleanup")
    print("-" * 60)

    marker1 = 'SELL FAILED FOR {ticker}! This is a critical error!'
    if marker1 in content:
        idx = content.index(marker1)
        # Find the 'else:' line before it
        block_start = content.rfind('        else:\n', 0, idx)
        # Find 'return success' after it
        ret_idx = content.index('return success', idx)
        block_end = ret_idx + len('return success')

        old_block = content[block_start:block_end]

        new_block = '''        else:
            # v10.6: Check if position is actually gone from Alpaca
            position_gone = False
            try:
                broker = self.execution_engine.broker
                if broker:
                    try:
                        check_pos = broker.get_position(ticker)
                        if check_pos and float(check_pos.qty) > 0:
                            pprint(f"  SELL FAILED FOR {ticker}! Position still exists at Alpaca!")
                        else:
                            position_gone = True
                    except Exception as pos_err:
                        if 'position does not exist' in str(pos_err).lower():
                            position_gone = True
                        else:
                            pprint(f"  SELL FAILED FOR {ticker}! Error checking: {pos_err}")
                else:
                    pprint(f"  SELL FAILED FOR {ticker}! No broker connection!")
            except Exception as check_err:
                pprint(f"  SELL FAILED FOR {ticker}! Check error: {check_err}")

            if position_gone:
                pprint(f"  ALREADY SOLD EXTERNALLY: {ticker} not found at Alpaca!")
                pprint(f"  Position was closed outside the bot. Cleaning up...")

                self.trades_today += 1
                self.pnl_today += pnl_dollars

                if pnl_dollars >= 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1

                self.pdt_tracker.record_sell(ticker)
                self.swing_strategy.record_exit(ticker, pnl_dollars)
                self.position_entry_times.pop(ticker, None)
                if hasattr(self, 'closed_eod_tickers'):
                    self.closed_eod_tickers.add(ticker)

                if self.loss_prevention:
                    self.loss_prevention.record_trade_result(pnl_dollars)

                self.reporter.log_trade({
                    'ticker': ticker, 'action': 'SELL', 'quantity': quantity,
                    'price': current_price, 'pnl': pnl_dollars,
                    'reason': f"EXTERNAL_CLOSE ({reason})"
                })

                pprint(f"  EXTERNAL CLOSE RECORDED: {ticker} | P&L: ${pnl_dollars:+.2f}")
                success = True

        pprint(f"")
        return success'''

        content = content.replace(old_block, new_block, 1)
        print(f"  PATCHED: Ghost cleanup after failed sell")
        changes += 1
    elif 'ALREADY SOLD EXTERNALLY' in content:
        print(f"  SKIP: Already patched (ghost cleanup)")
    else:
        print(f"  FAILED: Could not find SELL FAILED pattern")

    # ══════════════════════════════════════════════════════════════
    # FIX 2: Deduplicate exit signals
    # ══════════════════════════════════════════════════════════════
    print()
    print("FIX 2: Deduplicate exit signals")
    print("-" * 60)

    # Add processed set before exit loop
    marker2a = '            for sig in exit_signals:\n                ticker = sig.get(\'ticker\')'
    if marker2a in content and 'processed_exit_tickers' not in content:
        replacement2a = '            processed_exit_tickers = set()  # v10.6: Prevent duplicate exits\n            for sig in exit_signals:\n                ticker = sig.get(\'ticker\')'
        content = content.replace(marker2a, replacement2a, 1)
        print(f"  PATCHED: Added processed_exit_tickers set")
        changes += 1
    elif 'processed_exit_tickers' in content:
        print(f"  SKIP: Already patched (dedup set)")
    else:
        print(f"  FAILED: Could not find exit loop pattern")

    # Add skip check after ticker extraction
    marker2b = '                # v10.1: Skip PDT-blocked tickers immediately (no log spam)\n                if ticker in self.pdt_blocked_tickers:\n                    continue'
    if marker2b in content and 'processed_exit_tickers' not in content.split(marker2b)[0].split('processed_exit_tickers = set()')[-1] if 'processed_exit_tickers = set()' in content else True:
        # Only add skip if not already there
        if 'Already processed exit this cycle' not in content:
            replacement2b = '                # v10.6: Skip duplicate exits for same ticker\n                if ticker in processed_exit_tickers:\n                    pprint(f"  [SKIP] {ticker}: Already processed exit this cycle")\n                    continue\n                \n                # v10.1: Skip PDT-blocked tickers immediately (no log spam)\n                if ticker in self.pdt_blocked_tickers:\n                    continue'
            content = content.replace(marker2b, replacement2b, 1)
            print(f"  PATCHED: Added duplicate exit skip check")
            changes += 1
        else:
            print(f"  SKIP: Already patched (duplicate skip)")
    else:
        print(f"  SKIP: PDT-blocked pattern not found or already patched")

    # Mark ticker after successful sell
    sell_complete_marker = 'SELL COMPLETE: {ticker} | P&L: ${actual_pnl:+.2f}'
    if sell_complete_marker in content and 'processed_exit_tickers.add' not in content:
        idx = content.index(sell_complete_marker)
        line_end = content.index('\n', idx)
        old_line = content[content.rfind('\n', 0, content.rfind('pprint', 0, idx)) + 1:line_end]
        new_line = old_line + '\n            processed_exit_tickers.add(ticker)  # v10.6: Mark processed'
        content = content.replace(old_line, new_line, 1)
        print(f"  PATCHED: Mark ticker processed after successful sell")
        changes += 1
    elif 'processed_exit_tickers.add' in content:
        print(f"  SKIP: Already patched (mark processed)")

    # ══════════════════════════════════════════════════════════════
    # WRITE AND VERIFY
    # ══════════════════════════════════════════════════════════════
    if content != original:
        # Syntax check before writing
        print()
        print("SYNTAX CHECK:")
        print("-" * 60)
        try:
            compile(content, 'main.py', 'exec')
            print("  main.py: OK")

            with open('main.py', 'w', encoding='utf-8') as f:
                f.write(content)

        except SyntaxError as e:
            print(f"  SYNTAX ERROR at line {e.lineno}: {e.msg}")
            print(f"  Restoring backup...")
            with open(backup, 'r', encoding='utf-8') as f:
                with open('main.py', 'w', encoding='utf-8') as fw:
                    fw.write(f.read())
            print(f"  Restored. No changes applied.")
            changes = 0

    # ══════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if changes > 0:
        print(f"  {changes} patch(es) applied to main.py")
        print()
        print("  WHAT THIS FIXES:")
        print("  1. When Alpaca already sold a position externally,")
        print("     bot detects 'position does not exist' and cleans up")
        print("     (records P&L, updates win/loss, removes from tracker)")
        print("  2. Morning dump + stop loss won't both fire for same ticker")
        print("     (second signal is skipped)")
        print()
        print("  RESTART: python main.py --mode live")
    else:
        print("  No changes applied")

    print("=" * 60)


if __name__ == '__main__':
    main()
