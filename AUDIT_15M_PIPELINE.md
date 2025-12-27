# 15m Pipeline Audit - Summary

## Issues Found & Fixed

### ✅ 1. OHLCV Loading - VERIFIED CORRECT
- **Status:** ✅ Working correctly
- **Evidence:** `tools/diagnose_ohlcv.py` confirms:
  - Timeframe: 15m ✅
  - Timestamp spacing: 15.0 minutes ✅
  - Data freshness: < 30 minutes ✅
- **No changes needed**

### ✅ 2. Bar Timestamp Detection - FIXED
- **Issue:** `current_bar_ts = bar_ts or _now()` was using current time instead of actual bar timestamp
- **Fix:** Now uses timestamp from latest OHLCV bar if `bar_ts` not provided
- **Location:** `engine_alpha/loop/autonomous_trader.py` line ~937
- **Change:** Uses `rows[-1].get("ts")` from OHLCV data for accurate bar detection

### ⚠️ 3. Missing Continuous Loop - CREATED
- **Issue:** No continuous loop calling `run_step_live()` for new bars
- **Fix:** Created `tools/run_paper_loop.py` that:
  - Detects new 15m bars
  - Calls `run_step_live()` for each new bar
  - Waits appropriately between checks
- **Usage:** `python tools/run_paper_loop.py`

### ✅ 4. Paper Mode Execution Path - VERIFIED CORRECT
- **Status:** ✅ Execution path is correct
- **Flow:**
  1. `run_step_live()` → builds SignalContext from 15m OHLCV ✅
  2. Computes signals, regime, drift, confidence ✅
  3. Calls `should_enter_trade()` / `should_exit_trade()` ✅
  4. Calls `open_if_allowed()` / `close_now()` ✅
  5. Writes to `reports/trades.jsonl` via `_append_trade()` ✅
  6. Updates PF reports (only if NOT DRY_RUN) ✅
- **DRY_RUN guards:** Correctly protect PF + trades writes ✅

### ✅ 5. EXIT-DEBUG Logging - FIXED
- **Issue:** EXIT-DEBUG printed even when decision was to hold
- **Fix:** Only prints when `DEBUG_SIGNALS=1` and actual exit is happening
- **Location:** `engine_alpha/loop/autonomous_trader.py` line ~845

## Root Cause Analysis

**Why ETHUSDT stuck at 4 trades:**

1. **No continuous loop** - `run_step_live()` was designed to be called once per bar, but there was no scheduler/loop calling it
2. **Bar detection** - Used `_now()` instead of actual bar timestamp, causing incorrect "new bar" detection

## How to Run Paper Mode Now

### Option 1: Continuous Loop (Recommended)
```bash
# Ensure NOT in dry-run
unset MODE
unset CHLOE_DRY_RUN

# Run continuous loop
python tools/run_paper_loop.py
```

This will:
- Detect new 15m bars automatically
- Call `run_step_live()` for each new bar
- Log trades to `reports/trades.jsonl`
- Update PF reports

### Option 2: Manual Calls (Testing)
```bash
# Call once per bar manually
python -c "from engine_alpha.loop.autonomous_trader import run_step_live; run_step_live()"
```

## Verification Steps

### 1. Verify OHLCV Loading
```bash
python tools/diagnose_ohlcv.py
```

Expected output:
- ✅ Timeframe: 15m
- ✅ Average interval: 15.0 minutes
- ✅ Data is fresh

### 2. Run Dry-Run Test
```bash
python tools/run_dry_run.py --steps 5 --live
```

Expected:
- ✅ Timeframe: 15m
- ✅ Decisions logged
- ✅ No writes to real trades.jsonl

### 3. Run Paper Mode
```bash
unset MODE
unset CHLOE_DRY_RUN
python tools/run_paper_loop.py
```

Expected:
- ✅ New bars detected
- ✅ Trades logged to `reports/trades.jsonl`
- ✅ PF reports updated

### 4. Monitor Progress
```bash
# In another terminal
./tools/check_status.sh
python tools/monitor_status.py
tail -5 reports/trades.jsonl | jq .
```

## Files Changed

1. **`engine_alpha/loop/autonomous_trader.py`**
   - Fixed bar timestamp detection (uses OHLCV bar timestamp)
   - Added BAR-DEBUG logging (when DEBUG_SIGNALS=1)
   - Fixed EXIT-DEBUG to only print on actual exits

2. **`tools/run_paper_loop.py`** (NEW)
   - Continuous loop for paper trading
   - Detects new 15m bars
   - Calls `run_step_live()` appropriately

3. **`tools/diagnose_ohlcv.py`** (NEW)
   - Diagnostic tool to verify OHLCV loading
   - Checks timeframe, spacing, freshness

## Next Steps

1. ✅ Run `python tools/diagnose_ohlcv.py` to verify data loading
2. ✅ Run `python tools/run_paper_loop.py` to start continuous paper trading
3. ✅ Monitor with `./tools/check_status.sh` and `python tools/monitor_status.py`
4. ✅ After 50-100 trades, run GPT tuner: `python tools/run_threshold_tuner.py`

## Remaining TODOs

- [ ] Consider adding a systemd service or cron job for `run_paper_loop.py`
- [ ] Add monitoring/alerting if loop stops unexpectedly
- [ ] Consider adding a "backfill" mode to process historical bars if loop was down

## Summary

**What was broken:**
- No continuous loop calling `run_step_live()` for new bars
- Bar timestamp detection used current time instead of actual bar timestamp
- EXIT-DEBUG logging printed even when decision was to hold

**What was fixed:**
- Bar detection now uses actual OHLCV bar timestamps (from `rows[-1].get("ts")`)
- Created continuous loop script (`tools/run_paper_loop.py`)
- Fixed EXIT-DEBUG logging to only print when `DEBUG_SIGNALS=1` and actual exit occurs
- Added BAR-DEBUG logging (when `DEBUG_SIGNALS=1`) to track new bar detection

**Confirmation:**
- OHLCV loading: ✅ Correct (15m, proper spacing, verified via `diagnose_ohlcv.py`)
- Execution path: ✅ Correct (paper mode writes trades via `_append_trade()`)
- Bar detection: ✅ Fixed (uses actual bar timestamps from OHLCV)
- Continuous loop: ✅ Created (`tools/run_paper_loop.py`)
- `run_step_live()` execution: ✅ Verified working

**Expected outcome:**
- ETHUSDT trades should increase beyond 4 once `run_paper_loop.py` is running
- New trades logged every 15 minutes when conditions are met
- PF reports update correctly in paper mode

## How to Run Paper Mode

**Start continuous loop:**
```bash
unset MODE
unset CHLOE_DRY_RUN
python tools/run_paper_loop.py
```

**Monitor progress:**
```bash
# In another terminal
./tools/check_status.sh
python tools/monitor_status.py
tail -5 reports/trades.jsonl | jq .
```

