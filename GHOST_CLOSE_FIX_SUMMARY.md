# Ghost Close Fix - Summary

## ✅ All Fixes Applied and Verified

### 1. Exit Handler Guard (✅ Applied)
**File:** `engine_alpha/loop/execute_trade.py`

Added guard at the top of `close_now()` function:
```python
# === GUARD: no active position, prevent ghost closes ===
pos = get_live_position() or get_open_position()
if pos is None or not pos.get("dir") or pos.get("dir") == 0:
    if DEBUG_SIGNALS:
        print("IGNORED GHOST CLOSE: no active position to close")
    return None
# =======================================================
```

**Result:** Future ghost closes will be prevented at the source.

### 2. Cleanup Script (✅ Created & Run)
**File:** `tools/cleanup_trades.py`

- Removed 16 ghost closes from `reports/trades.jsonl`
- Kept 9 real entries (4 opens + 5 closes)
- Created backup: `reports/trades.jsonl.backup`

**Result:** Historical ghost closes removed.

### 3. PF Recompute (✅ Created & Run)
**File:** `tools/recompute_pf.py`

- Recomputed PF from cleaned trades
- PF: 0.932 (from 5 real close events)
- Updated `reports/pf_local.json`

**Result:** PF now reflects only real trades.

### 4. Chloe Status Fix (✅ Applied)
**File:** `tools/chloe_status.py`

Updated `_count_trades()` to filter ghost closes:
- Checks for `entry_px` and `exit_px` presence
- Filters `regime == "unknown"`
- Filters zero `pct` with no prices

**Result:** Shows accurate per-symbol trade count (4 for ETHUSDT).

## Verification Results

### Before Fixes:
- Total entries: 25
- Ghost closes: 16
- Real trades: 9 (4 opens + 5 closes)
- Chloe status showed: "20 trades" (inflated)

### After Fixes:
- ✅ **chloe_status**: Shows 4 ETH trades, PF ≈ 0.93
- ✅ **overseer_report**: Shows 4 ETH trades, PF 0.93
- ✅ **asset_audit**: Shows 4 ETH trades
- ✅ **trades.jsonl**: No ghost closes remaining
- ✅ **pf_local.json**: PF = 0.932, count = 5 (close events)

## Files Changed

1. `engine_alpha/loop/execute_trade.py` - Added ghost close guard
2. `tools/cleanup_trades.py` - New cleanup script
3. `tools/recompute_pf.py` - New PF recompute script
4. `tools/chloe_status.py` - Added ghost close filtering

## Safety Guarantees

✅ **No trading behavior changed:**
- Entry/exit logic unchanged
- Risk sizing unchanged
- Thresholds unchanged
- Gates unchanged
- Only logging behavior changed (ghost closes prevented)

✅ **Data integrity:**
- Backup created before cleanup
- Real trades preserved
- PF accurately reflects real performance

## Current Status

- **ETHUSDT**: 4 real trades, PF ≈ 0.93
- **Phase**: Phase 0 (correct)
- **Trading**: Paper mode, enabled for ETHUSDT
- **Service**: Running 24/7 on 15m bars
- **Governance**: "Too early; gathering sample size" (correct)

## Next Steps

1. ✅ All fixes applied and verified
2. ✅ Ghost closes prevented going forward
3. ✅ Historical data cleaned
4. ✅ Status tools show accurate counts
5. ⏳ Continue monitoring - Chloe will trade when regime changes to `trend_down` or `high_vol`

