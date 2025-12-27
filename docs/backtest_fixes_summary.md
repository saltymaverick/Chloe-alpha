# Backtest Divergence Fixes - Summary

## Critical Bugs Fixed

### Bug #1: `decide()` Used Wrong Regime ✅ FIXED

**Problem**: 
- `decide()` computed regime from signal data (via `get_regime()`)
- `_compute_council_aggregation()` inside `decide()` used this signal-based regime
- But `run_step_live` overrides regime with `price_based_regime` AFTER calling `decide()`
- Result: Council aggregation used wrong regime

**Fix**: 
- Added `regime_override` parameter to `decide()` function
- `run_step_live` now passes `price_based_regime` to `decide()` so aggregation uses correct regime

**Files Changed**:
- `engine_alpha/core/confidence_engine.py`: Added `regime_override` parameter to `decide()`
- `engine_alpha/loop/autonomous_trader.py`: Pass `regime_override=price_based_regime` to `decide()`

### Bug #2: Manual Aggregation Used Wrong Weights ✅ FIXED

**Problem**:
- After calling `decide()`, `run_step_live` manually recomputed `final_score`
- Manual computation used `COUNCIL_WEIGHTS` (legacy weights with "trend", "chop", "high_vol" keys)
- But `_compute_council_aggregation()` uses `REGIME_BUCKET_WEIGHTS` (per-regime weights with "trend_up", "trend_down", etc.)
- These are DIFFERENT weight systems!

**Fix**:
- Changed manual aggregation to use `REGIME_BUCKET_WEIGHTS` instead of `COUNCIL_WEIGHTS`
- Removed double-masking (decide() already applies masking)
- Simplified aggregation to use `REGIME_BUCKET_WEIGHTS` directly

**Files Changed**:
- `engine_alpha/loop/autonomous_trader.py`: Use `REGIME_BUCKET_WEIGHTS` in manual aggregation

## Remaining Issues to Verify

### Issue #3: Mock OHLCV in Backtests

**Check**: Verify `get_live_ohlcv` mock returns correct current bar

**Location**: `tools/backtest_harness.py:263-284`

**Status**: ✅ Looks correct - mock returns window ending at current bar, `[-1]` is current bar

### Issue #4: Entry/Exit Price Fetching

**Check**: Verify `_try_open` and `close_now` get prices from current bar correctly

**Location**: 
- `engine_alpha/loop/autonomous_trader.py:1028` (entry price)
- `engine_alpha/loop/autonomous_trader.py:1228` (exit price)

**Status**: ✅ Uses `get_live_ohlcv(limit=1)[-1]` which should work with mock

### Issue #5: P&L Calculation

**Check**: Verify `pct` calculation uses `entry_px` and `exit_px` correctly

**Location**: `engine_alpha/loop/autonomous_trader.py:1244-1265`

**Status**: ✅ Uses price-based calculation: `(exit_px - entry_px) / entry_px * dir`

## Testing

Use `tools/backtest_step_diagnostic.py` to trace a single step:

```bash
python3 -m tools.backtest_step_diagnostic \
  --symbol ETHUSDT \
  --timeframe 1h \
  --timestamp 2021-05-12T14:00:00Z \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --window 200
```

This will show:
- Regime classification
- Confidence aggregation
- Entry gating decisions
- Whether trades open/close
- P&L calculation

## Expected Behavior After Fixes

1. **Regime classification**: Same in live and backtest (uses price-based regime)
2. **Confidence aggregation**: Same in live and backtest (uses correct regime + REGIME_BUCKET_WEIGHTS)
3. **Entry decisions**: Same thresholds, same gating logic
4. **Exit decisions**: Same logic, same P&L calculation

## Next Steps

1. Run `backtest_step_diagnostic` on a known timestamp to verify behavior
2. Run a full backtest and compare regime distribution with live
3. Verify meaningful TP/SL closes appear in backtests
4. Compare PF by regime between backtest and live (should be similar for same periods)


