# Chloe Real-Time HUD - Implementation Summary

## ✅ Implementation Complete

### File Created
- **`tools/hud.py`** - Real-time terminal HUD script

### Features

**Real-time updates:**
- Clears screen every second
- Reads current status from JSON/log files
- Displays concise status view

**Display sections:**
1. **Header** - Time and phase
2. **Trading enabled** - List of symbols enabled for paper trading
3. **Asset status** - ETHUSDT and MATICUSDT trades and PF
4. **Recent ETH trades** - Last 3 close events with details
5. **Recent MATIC decisions** - Last 5 decisions from log
6. **Global PF** - Overall performance factor summary

**Data sources:**
- `config/trading_enablement.json` - Phase and enabled symbols
- `reports/scorecards/asset_scorecards.json` - Asset metrics
- `reports/pf_local.json` - Global PF
- `reports/trades.jsonl` - Trade history
- `logs/matic_decisions.log` - MATIC decision log (optional)

### Safety Guarantees

✅ **Read-only:**
- Only reads files, never writes
- No trading behavior changes
- No state modifications

✅ **Error handling:**
- Gracefully handles missing files
- Continues running if individual files fail to load
- Exits cleanly on Ctrl+C

✅ **Non-interactive:**
- No user input required
- Updates automatically
- Ctrl+C to exit

### Usage

```bash
# Run the HUD
python3 -m tools.hud

# Exit with Ctrl+C
```

### Display Format

```
============================================================
CHLOE REAL-TIME HUD
============================================================
Time:  2025-11-29 03:45:00 UTC
Phase: phase_0

Trading enabled (paper): ETHUSDT, MATICUSDT

ASSET STATUS
------------------------------------------------------------
ETHUSDT:   trades=4 (scorecard: 4), PF=0.932
MATICUSDT: trades=0 (scorecard: 0), PF=—

RECENT ETH TRADES (closes)
------------------------------------------------------------
  2025-11-25 23:00:09 | SHORT | pct=-0.0194 | regime=trend_up   | exit=sl
  2025-11-26 03:15:26 | FLAT  | pct=+0.0000 | regime=trend_down | exit=decay

RECENT MATIC DECISIONS
------------------------------------------------------------
  BLOCK    | chop         | FLAT  | conf=0.43 | CHOP_BLOCK
  BLOCK    | chop         | FLAT  | conf=0.43 | CHOP_BLOCK

PF (global)
------------------------------------------------------------
  PF=0.932  count=5  window=150

Press Ctrl+C to exit.
```

### Implementation Details

**Key functions:**
- `clear_screen()` - Clears terminal (cross-platform)
- `load_json_safe()` - Safely loads JSON with fallback
- `read_last_lines()` - Reads last N lines from log file
- `get_asset_card()` - Extracts asset scorecard from data
- `count_trades_from_jsonl()` - Counts real trades (filters ghosts)
- `get_recent_trades()` - Gets recent close trades
- `format_timestamp()` - Formats ISO timestamps for display

**Error handling:**
- All file operations wrapped in try/except
- Missing files return empty defaults
- Invalid JSON returns empty dict/list
- Continues running even if individual data sources fail

**Data accuracy:**
- Counts trades from `trades.jsonl` directly (more accurate)
- Also shows scorecard counts for comparison
- Filters ghost closes (no entry_px/exit_px, regime=unknown)

### Testing

✅ **Import test:** All functions import correctly
✅ **Data loading:** Successfully loads all data sources
✅ **Trade counting:** Accurately counts trades from jsonl
✅ **Error handling:** Handles missing files gracefully
✅ **Display:** Formats output correctly

### Files Changed

1. ✅ `tools/hud.py` - New HUD script (created)

### Verification

```bash
# Test run (will timeout after 3 seconds)
timeout 3 python3 -m tools.hud

# Full run
python3 -m tools.hud
# Press Ctrl+C to exit
```

### Next Steps

- HUD is ready to use
- Run `python3 -m tools.hud` to start monitoring
- Updates every second automatically
- View real-time status of ETHUSDT and MATICUSDT

