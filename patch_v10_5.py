"""
QUANTUM TRADING SYSTEM v10.5 PATCHER
═══════════════════════════════════════════════════════════════════════════════
Run this script from C:\quantum-trading-system to apply two critical fixes:

FIX 1: DST TIMEZONE BUG (ALL FILES)
  Old: EST = timezone(timedelta(hours=-5))     ← Always UTC-5 (EST)
  New: EST = ZoneInfo('America/New_York')       ← Auto EST/EDT based on date
  
  This caused the Mar 24 CF overnight hold: bot thought it was 3:21 PM
  when it was actually 4:21 PM. EOD liquidation fired after market close.
  Alpaca canceled the sell. CF stuck overnight.

FIX 2: TIGHTER STOP LOSS (swing_strategy.py only)
  Old: self.stop_loss_pct = config.get('swing_stop_loss_pct', 0.025)  ← 2.5%
  New: self.stop_loss_pct = config.get('swing_stop_loss_pct', 0.015)  ← 1.5%
  
  2.5% was too wide for $500 account. CF sat at -1.27% for hours with no
  exit trigger. 1.5% would have cut it at -1.5% ($-1.91) instead of
  holding until EOD. ARE's -0.71% dip on Mar 17 still would NOT have
  been stopped out at 1.5%.

USAGE:
  cd C:\quantum-trading-system
  python patch_v10_5.py
  
  Then restart the bot: python main.py --mode live
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import re
from datetime import datetime

# Files that need the timezone fix
TIMEZONE_FILES = [
    'main.py',
    'modules/swing_strategy.py',
    'modules/adaptive_intelligence.py',
    'modules/loss_prevention.py',
    'modules/opportunity_scanner.py',
    'modules/session_reporter.py',
]

# The old broken timezone pattern and the new fix
OLD_TIMEZONE = 'EST = timezone(timedelta(hours=-5))'
NEW_TIMEZONE = "EST = ZoneInfo('America/New_York')"

# Import that needs to be added
ZONEINFO_IMPORT = 'from zoneinfo import ZoneInfo'

def patch_file(filepath, changes_made):
    """Apply patches to a single file"""
    if not os.path.exists(filepath):
        print(f"  ⚠️  SKIP: {filepath} not found")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    file_changes = []
    
    # FIX 1: Replace hardcoded EST timezone
    if OLD_TIMEZONE in content:
        content = content.replace(OLD_TIMEZONE, NEW_TIMEZONE)
        file_changes.append("timezone: UTC-5 → America/New_York")
    
    # FIX 1b: Add zoneinfo import if not present
    if ZONEINFO_IMPORT not in content and NEW_TIMEZONE in content:
        # Find the right place to add the import
        # Look for 'from datetime import' line and add after it
        datetime_import = re.search(r'(from datetime import[^\n]+\n)', content)
        if datetime_import:
            insert_pos = datetime_import.end()
            content = content[:insert_pos] + ZONEINFO_IMPORT + '\n' + content[insert_pos:]
            file_changes.append("added: from zoneinfo import ZoneInfo")
        else:
            # Fallback: add at top after other imports
            import_section = re.search(r'(import \w+\n)', content)
            if import_section:
                insert_pos = import_section.end()
                content = content[:insert_pos] + ZONEINFO_IMPORT + '\n' + content[insert_pos:]
                file_changes.append("added: from zoneinfo import ZoneInfo")
    
    # FIX 2: Tighter stop loss (swing_strategy.py only)
    if 'swing_strategy' in filepath:
        old_stop = "self.stop_loss_pct = config.get('swing_stop_loss_pct', 0.025)"
        new_stop = "self.stop_loss_pct = config.get('swing_stop_loss_pct', 0.015)  # v10.5: tightened from 2.5% to 1.5%"
        if old_stop in content:
            content = content.replace(old_stop, new_stop)
            file_changes.append("stop_loss: 2.5% → 1.5%")
    
    if content != original:
        # Backup original
        backup = filepath + '.bak_v10_4'
        if not os.path.exists(backup):  # Don't overwrite existing backups
            with open(backup, 'w', encoding='utf-8') as f:
                f.write(original)
        
        # Write patched file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        changes_made.append((filepath, file_changes))
        print(f"  ✅ PATCHED: {filepath}")
        for change in file_changes:
            print(f"       → {change}")
        return True
    else:
        print(f"  ℹ️  NO CHANGE: {filepath} (already patched or pattern not found)")
        return False


def verify_fix():
    """Verify the timezone fix works"""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    
    try:
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('America/New_York')
        now = datetime.now(eastern)
        print(f"  Current Eastern Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"  UTC Offset: {now.strftime('%z')}")
        
        offset_hours = now.utcoffset().total_seconds() / 3600
        if offset_hours == -4:
            print(f"  ✅ DST Active (EDT = UTC-4) — CORRECT for Mar-Nov")
        elif offset_hours == -5:
            print(f"  ✅ Standard Time (EST = UTC-5) — CORRECT for Nov-Mar")
        else:
            print(f"  ⚠️  Unexpected offset: UTC{offset_hours:+.0f}")
        
        return True
    except ImportError:
        print("  ❌ ERROR: zoneinfo not available!")
        print("  Requires Python 3.9+. Your version:", sys.version)
        return False
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        return False


def also_patch_config():
    """Update config.json stop loss to match"""
    config_path = 'config.json'
    if not os.path.exists(config_path):
        return
    
    with open(config_path, 'r') as f:
        content = f.read()
    
    original = content
    
    # Update swing_stop_loss_pct if present
    content = content.replace('"swing_stop_loss_pct": 0.025', '"swing_stop_loss_pct": 0.015')
    content = content.replace('"stop_loss_pct": 0.025', '"stop_loss_pct": 0.015')
    
    if content != original:
        backup = config_path + '.bak_v10_4'
        if not os.path.exists(backup):
            with open(backup, 'w') as f:
                f.write(original)
        with open(config_path, 'w') as f:
            f.write(content)
        print(f"  ✅ PATCHED: {config_path}")
        print(f"       → stop_loss_pct: 0.025 → 0.015")
    else:
        print(f"  ℹ️  NO CHANGE: {config_path}")


def main():
    print("=" * 60)
    print("  QUANTUM TRADING SYSTEM v10.5 PATCHER")
    print("  Fixes: DST timezone + tighter stop loss (1.5%)")
    print("=" * 60)
    print()
    
    # Check we're in the right directory
    if not os.path.exists('main.py'):
        print("❌ ERROR: main.py not found!")
        print("   Run this script from C:\\quantum-trading-system")
        print(f"   Current directory: {os.getcwd()}")
        sys.exit(1)
    
    if not os.path.exists('modules'):
        print("❌ ERROR: modules/ directory not found!")
        sys.exit(1)
    
    # Verify zoneinfo works before patching
    print("PRE-CHECK:")
    if not verify_fix():
        print("\n❌ Cannot proceed — zoneinfo not available")
        sys.exit(1)
    
    print("\n" + "-" * 60)
    print("PATCHING FILES:")
    print("-" * 60)
    
    changes_made = []
    
    for filepath in TIMEZONE_FILES:
        patch_file(filepath, changes_made)
    
    print()
    print("CONFIG:")
    also_patch_config()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if changes_made:
        print(f"  ✅ {len(changes_made)} file(s) patched successfully")
        print(f"  📁 Backups saved as *.bak_v10_4")
        print()
        print("  CHANGES APPLIED:")
        for filepath, changes in changes_made:
            print(f"    {filepath}:")
            for c in changes:
                print(f"      • {c}")
    else:
        print("  ℹ️  No changes needed — files already patched")
    
    print()
    print("  NEXT STEPS:")
    print("  1. Restart the bot:  python main.py --mode live")
    print("  2. Verify startup shows correct ET time")
    print("  3. CF is still open overnight — morning dump will sell it tomorrow")
    print()
    print("=" * 60)


if __name__ == '__main__':
    main()
