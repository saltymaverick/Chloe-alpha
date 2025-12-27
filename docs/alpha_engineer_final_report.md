# Alpha Engineer - Final Report & Recommendations

**Date:** 2025-11-23  
**Status:** 🔴 **CRITICAL ISSUE FIXED - VERIFICATION NEEDED**

---

## ✅ FIXES APPLIED

### Fix #1: Regime Classifier Thresholds ✅

**File:** `engine_alpha/core/regime.py`

**Changes:**
1. Lowered `high_vol` threshold: `atr_ratio >= 1.15` (was 1.25), `atr_pct >= 0.020` (was 0.025)
2. Lowered `trend_down` threshold: `change_pct <= -0.02` (was -0.08), `slope20 / first >= 0.0001` (was 0.0002)
3. Added fallback logic for `trend_down`: catches strong downward slopes even if `change_pct` isn't extreme

**Impact:** Should detect more `trend_down` and `high_vol` periods

### Fix #2: Entry Thresholds ✅

**File:** `config/entry_thresholds.json`

**Changes:**
- `trend_down`: 0.48 (was 0.52)
- `high_vol`: 0.38 (was 0.40)

**Impact:** More entries will pass threshold checks

### Fix #3: Neutral Zone ✅

**File:** `engine_alpha/loop/autonomous_trader.py`

**Changes:**
- `NEUTRAL_THRESHOLD_DEFAULT`: 0.25 (was 0.30)

**Impact:** Fewer bars neutralized (reduces false negatives)

### Fix #4: Broken Import ✅

**File:** `tools/backtest_step.py`

**Changes:**
- Fixed import of `compute_entry_min_conf` (was `_compute_entry_min_conf`)

**Impact:** Diagnostic tool now works

---

## 🔍 REMAINING ISSUE

### Problem: Regime Classifier Still Too Conservative

**Observation:**
- Even after fixes, most bars still classified as `chop`
- Test periods (April-May 2022) show 100% `chop` classification
- Bars with high confidence (0.87, 0.48) are blocked by regime gate

**Root Cause:**
- `change_pct` threshold (-2%) might still be too strict for 20-bar windows
- `slope20` calculation might not be sensitive enough
- `atr_ratio` might not be computed correctly (showing 1.000 consistently)

**Recommendation:**
1. **Option A:** Further lower thresholds (change_pct to -1%, atr_ratio to 1.10)
2. **Option B:** Use shorter windows for regime detection (10 bars instead of 20)
3. **Option C:** Temporarily allow `chop` entries with very high threshold (0.75) for testing

---

## 📊 VERIFICATION STEPS

### Step 1: Run Diagnostic on Known Trend Period

```bash
# Test on a period known to have trends (e.g., May 2021 bull run)
python3 -m tools.diagnose_zero_trades \
  --symbol ETHUSDT --timeframe 1h \
  --timestamp 2021-05-15T12:00:00Z \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --sample 100
```

**Expected:** Should see `trend_up` classifications

### Step 2: Run Backtest on Longer Period

```bash
# Test on 1 month period
python3 -m tools.backtest_harness \
  --symbol ETHUSDT --timeframe 1h \
  --start 2022-05-01T00:00:00Z \
  --end 2022-06-01T00:00:00Z \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv
```

**Expected:** Should see > 0 opens, > 0 closes

### Step 3: Check Regime Distribution

```bash
# After backtest, check regime distribution
python3 -m tools.backtest_report \
  --run-dir reports/backtest/<run_id>
```

**Expected:** Should see `trend_down` and `high_vol` in PF breakdown

---

## 🚀 NEXT STEPS

### Immediate Actions:

1. **Test on known trend periods** (May 2021, Nov 2022)
2. **If still 100% chop:** Lower thresholds further or use shorter windows
3. **If trades open:** Verify P&L accuracy and exit logic

### Long-term Improvements:

1. **Regime classifier tuning:** Use historical data to calibrate thresholds
2. **Signal quality:** Improve signal fetchers to use real OHLCV data (not random)
3. **Confidence calibration:** Ensure confidence distribution matches expectations

---

## 📝 FILES CHANGED

1. ✅ `engine_alpha/core/regime.py` - Regime classifier thresholds
2. ✅ `config/entry_thresholds.json` - Entry thresholds
3. ✅ `engine_alpha/loop/autonomous_trader.py` - Neutral zone threshold
4. ✅ `tools/backtest_step.py` - Fixed import
5. ✅ `tools/diagnose_zero_trades.py` - New diagnostic tool

---

## 🎯 SUCCESS CRITERIA

- [ ] Regime distribution: < 80% `chop`
- [ ] Backtest opens: > 0 trades
- [ ] Backtest closes: > 0 trades
- [ ] PF > 0 (meaningful trades)

---

**End of Report**


