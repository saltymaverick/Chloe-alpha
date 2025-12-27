# Chloe Codebase Diagnostic Report

**Date:** 2025-11-23  
**Scope:** Full codebase analysis for logic bugs, inconsistencies, and structural issues

## Executive Summary

Found **7 critical issues** and **3 warnings** that could cause:
- Incorrect P&L calculations (units mismatch)
- Redundant/inefficient code paths
- Dead code that should be removed
- Potential inconsistencies between `decide()` output and manual aggregation

## Critical Issues

### Issue #1: P&L Units Mismatch - CRITICAL BUG

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 1184-1204, 1260, 1354

**Problem:**
- Exit logic (lines 1184-1204) sets `close_pct` using `final.get("conf", 0.0)` which is a **decimal** (0.0-1.0)
- Price-based calculation (line 1260) multiplies by 100.0 to get **percentage** (0.0-100.0)
- PnL extraction (line 1354) divides `close_pct` by 100.0, assuming it's a percentage
- **Result:** When using confidence-based exits, PnL is 100x too small (0.75 → 0.0075)

**Root Cause:**
The exit logic uses confidence values (decimals) directly as `close_pct`, but the PnL calculation expects percentages.

**Impact:**
- Equity calculations are wrong for confidence-based exits (TP/SL/drop/decay)
- Only price-based exits work correctly
- Backtest equity curves are incorrect

**Fix:**
```python
# Line 1184: Stop-loss
close_pct = -abs(float(final.get("conf", 0.0))) * 100.0  # Convert to percentage

# Line 1189: Take-profit  
close_pct = abs(float(final.get("conf", 0.0))) * 100.0  # Convert to percentage

# Lines 1196, 1199, 1204: Other exits
close_pct = float(final.get("conf", 0.0)) * 100.0 if same_dir else -float(final.get("conf", 0.0)) * 100.0
```

**OR** (better): Remove confidence-based `close_pct` entirely and always use price-based calculation (which is already implemented at lines 1250-1273).

### Issue #2: Redundant Manual Aggregation After `decide()`

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 736-792

**Problem:**
- `decide()` is called at line 700 and already computes `final_dir` and `final_conf`
- Code then manually recomputes aggregation at lines 736-792 with Phase 54 adjustments
- This creates two sources of truth that could diverge

**Root Cause:**
Phase 54 regime-aware bucket emphasis needs to be applied, but it's done AFTER `decide()` instead of inside it.

**Impact:**
- Potential inconsistencies if `decide()` logic changes
- Code duplication
- Harder to maintain

**Fix:**
Move Phase 54 adjustments into `confidence_engine.py`'s `_compute_council_aggregation()` function, or apply them to `decision["final"]` directly without recomputing.

**Recommended Fix:**
```python
# After line 700, apply Phase 54 adjustments to decision["final"] directly:
final_result = decision["final"]
final_score = final_result.get("final_score", 0.0)  # Need to expose this from decide()

# Apply Phase 54 adjustments
bucket_weight_adj = {name: 1.0 for name in BUCKET_ORDER}
if IS_PAPER_MODE:
    if regime in ("trend_down", "trend_up"):
        # Recompute with adjusted weights (simplified)
        # OR: just apply multiplier to final_score
        final_score *= 1.05  # Small boost for trend regimes

effective_final_dir = 1 if final_score > 0 else (-1 if final_score < 0 else 0)
effective_final_conf = min(abs(final_score), 1.0)
```

### Issue #3: Dead Code - Unused `_compute_entry_min_conf` Function

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 181-275

**Problem:**
- Function `_compute_entry_min_conf()` at line 181 is never called
- The code uses `compute_entry_min_conf()` at line 152 instead
- Contains complex regime logic that's not being used

**Impact:**
- Code confusion
- Maintenance burden
- Potential for accidental use

**Fix:**
Remove the unused function (lines 181-275).

### Issue #4: Legacy COUNCIL_WEIGHTS Reference (Not Actually Used)

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 708-712

**Problem:**
- Code checks if `regime_for_weights` is in `COUNCIL_WEIGHTS`
- But `COUNCIL_WEIGHTS` is never actually used (code uses `REGIME_BUCKET_WEIGHTS` instead)
- This is dead code that adds confusion

**Impact:**
- Code confusion
- Misleading comments

**Fix:**
Remove lines 708-712 (they're not used since manual aggregation uses `REGIME_BUCKET_WEIGHTS`).

### Issue #5: Exit Logic Uses Confidence Instead of Price-Based P&L

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 1184-1204

**Problem:**
- Exit conditions set `close_pct` using confidence values (lines 1184, 1189, 1196, 1199, 1204)
- Price-based P&L calculation exists (lines 1250-1273) but is only used if `close_pct` is None
- Since `close_pct` is always set, price-based calculation is never used

**Impact:**
- P&L doesn't reflect actual price movements
- Backtest results are inaccurate
- Live trading P&L is wrong

**Fix:**
Remove confidence-based `close_pct` assignments and always use price-based calculation:

```python
# Remove lines 1184, 1189, 1196, 1199, 1204 that set close_pct
# Instead, set exit flags and compute price-based pct at lines 1250-1273
```

### Issue #6: `run_step()` Function Still Uses Old Logic

**Location:** `engine_alpha/loop/autonomous_trader.py` lines 503-612

**Problem:**
- `run_step()` function (legacy) still uses confidence-based P&L (lines 575-585)
- This function may still be called by some tools
- Doesn't use price-based P&L calculation

**Impact:**
- Legacy code path has wrong P&L
- Tools using `run_step()` get incorrect results

**Fix:**
Update `run_step()` to use price-based P&L like `run_step_live()` does, or deprecate it.

### Issue #7: Missing `final_score` in `decide()` Return

**Location:** `engine_alpha/core/confidence_engine.py` line 546-558

**Problem:**
- `decide()` returns `final_dir` and `final_conf` but not `final_score`
- `autonomous_trader.py` needs `final_score` for Phase 54 adjustments (line 792)
- Code recomputes `final_score` manually instead

**Impact:**
- Redundant computation
- Potential for inconsistency

**Fix:**
Add `final_score` to `decide()` return value:

```python
# In confidence_engine.py, line 546-558:
return {
    "regime": regime,
    "buckets": buckets,
    "final": {
        "dir": final_result["dir"],
        "conf": final_result["conf"],
        "score": final_result["final_score"],  # Add this
    },
    "gates": {...},
}
```

## Warnings

### Warning #1: Inconsistent Regime Classification

**Location:** Multiple files

**Status:** ✅ Actually OK - `classify_regime()` is used consistently

The code correctly uses price-based regime classification everywhere. No fix needed.

### Warning #2: Neutral Zone Threshold Consistency

**Location:** `engine_alpha/core/confidence_engine.py`, `engine_alpha/loop/autonomous_trader.py`

**Status:** ✅ Actually OK - Both use `NEUTRAL_THRESHOLD = 0.30`

No fix needed - threshold is consistent.

### Warning #3: Entry Threshold Override Logic

**Location:** `engine_alpha/loop/autonomous_trader.py` line 152

**Status:** ⚠️ Missing TUNE_ENTRY_* support

The `compute_entry_min_conf()` function doesn't check for `TUNE_ENTRY_*` env vars, but the unused `_compute_entry_min_conf()` does. Since we're removing the unused function, we should add TUNE support to the active one if needed.

**Fix (if TUNE support is needed):**
```python
def compute_entry_min_conf(regime: str, risk_band: str | None) -> float:
    # Check for TUNE override
    env_map = {
        "trend_down": "TUNE_ENTRY_TREND_DOWN",
        "trend_up": "TUNE_ENTRY_TREND_UP",
        "chop": "TUNE_ENTRY_CHOP",
        "high_vol": "TUNE_ENTRY_HIGH_VOL",
    }
    env_var = env_map.get(regime)
    if env_var:
        override = os.getenv(env_var)
        if override is not None:
            try:
                return max(0.35, min(0.90, float(override)))
            except (ValueError, TypeError):
                pass
    
    # Normal logic...
    base = _ENTRY_THRESHOLDS.get(regime, ENTRY_THRESHOLDS_DEFAULT["chop"])
    # ... rest of function
```

## Consistency Matrix

| Component | Live | Backtest | Status |
|-----------|------|----------|--------|
| Regime classification | `classify_regime()` | `classify_regime()` | ✅ Consistent |
| Confidence aggregation | `decide()` + manual | `decide()` + manual | ⚠️ Redundant manual step |
| Entry thresholds | `compute_entry_min_conf()` | `compute_entry_min_conf()` | ✅ Consistent |
| Exit logic | Price-based (intended) | Price-based (intended) | ❌ Actually uses confidence |
| P&L calculation | Price-based | Price-based | ❌ Units mismatch |
| Neutral zone | 0.30 | 0.30 | ✅ Consistent |
| Regime gate | `regime_allows_entry()` | `regime_allows_entry()` | ✅ Consistent |

## Recommended Fix Priority

1. **P0 - Critical:** Fix P&L units mismatch (Issue #1, #5)
2. **P1 - High:** Remove dead code (Issue #3)
3. **P2 - Medium:** Simplify aggregation (Issue #2, #7)
4. **P3 - Low:** Clean up legacy references (Issue #4)

## Verification Steps

After applying fixes:

1. **Test P&L calculation:**
   ```bash
   # Run a backtest with known price movements
   python3 -m tools.backtest_harness --symbol ETHUSDT --timeframe 1h \
     --start 2022-04-01T00:00:00Z --end 2022-04-02T00:00:00Z
   
   # Check that pct values match actual price movements
   python3 -m tools.pf_doctor_filtered --run-dir <run_dir>
   ```

2. **Test entry logic:**
   ```bash
   # Verify entries use correct thresholds
   python3 -m tools.backtest_step --symbol ETHUSDT --timeframe 1h \
     --timestamp 2022-04-01T12:00:00Z --csv data/ohlcv/ETHUSDT_1h_merged.csv
   ```

3. **Test exit logic:**
   ```bash
   # Verify exits use price-based P&L
   # Check trades.jsonl - pct should match (exit_price - entry_price) / entry_price * dir * 100
   ```

## Files Changed

1. `engine_alpha/loop/autonomous_trader.py` - Fix P&L, remove dead code, simplify aggregation
2. `engine_alpha/core/confidence_engine.py` - Add `final_score` to return value
3. `engine_alpha/loop/execute_trade.py` - Verify pct units are consistent

## Next Steps

1. Apply fixes in priority order
2. Run comprehensive backtests to verify
3. Update documentation if needed
4. Consider deprecating `run_step()` if not needed


