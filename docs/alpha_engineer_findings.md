# Alpha Engineer - Root Cause Analysis & Fix Plan

**Date:** 2025-11-23  
**Status:** 🔴 **CRITICAL ISSUE IDENTIFIED**

---

## 🔴 ROOT CAUSE: Zero Trades Opening

### Diagnostic Results

**Sample:** 21 bars from 2022-04-15 (trend_down period)

**Findings:**
1. **100% classified as `chop`** - All 21 bars classified as `chop`
2. **Regime gate blocks all entries** - `regime_allows_entry()` only allows `trend_down` and `high_vol`
3. **Confidence distribution:** avg=0.28, min=0.00, max=0.85
4. **52.4% neutralized** - 11/21 bars neutralized by neutral zone (0.30 threshold)

### Entry Decision Flow

```
Bar → Regime Classification → Entry Gate → Threshold Check → Open Trade
 ↓              ↓                    ↓              ↓              ↓
chop      ❌ BLOCKED          (never reached)  (never reached)  ❌ NO TRADE
```

**Blockers:**
1. ❌ **REGIME_GATE:** `chop` not allowed (only `trend_down`/`high_vol`)
2. ⚠️ **THRESHOLD:** Even if allowed, `conf=0.54 < entry_min=0.75` for chop

---

## 🔍 Detailed Analysis

### Issue #1: Regime Classifier Too Conservative

**Problem:**
- Regime classifier (`classify_regime`) is classifying **everything as `chop`**
- Even during clear trend periods (2022 dump), it's not detecting `trend_down`
- Thresholds for trend detection are too strict

**Evidence:**
```
REGIME-SIMPLE: regime=chop slope5=-0.927500 slope20=-0.027895 hh=6 ll=6 atr_ratio=1.000 change_pct=-0.0002
```

**Root Cause:**
- `classify_regime()` uses `classify_regime_simple()` internally
- `classify_regime_simple()` requires:
  - `slope5 < -0.001` AND `ema20_slope < 0` AND `ll > hh` for `trend_down`
  - But `ema20_slope` is always 0.000000 (not computed correctly)
  - `atr_ratio > 1.5` for `high_vol` (too strict)

### Issue #2: Entry Thresholds Too High

**Problem:**
- `config/entry_thresholds.json` has:
  - `trend_down: 0.52` ✅ Reasonable
  - `high_vol: 0.40` ✅ Reasonable
  - `chop: 0.75` ❌ Very high (but doesn't matter since chop is blocked)

**Impact:**
- Even if regime was `trend_down` or `high_vol`, confidence might not reach thresholds
- Average confidence is 0.28, max is 0.85
- Only 1/21 bars had confidence >= 0.75

### Issue #3: Neutral Zone Too Aggressive

**Problem:**
- Neutral zone threshold is 0.30
- 52.4% of bars are neutralized (11/21)
- This zeros out `effective_final_dir` even when signals are present

**Impact:**
- Even if regime was allowed, many bars would be blocked by neutral zone

---

## 🛠️ FIX PLAN

### Fix #1: Improve Regime Classifier ✅ HIGH PRIORITY

**Goal:** Make regime classifier detect `trend_down` and `high_vol` more accurately

**Changes:**
1. Fix `ema20_slope` calculation in `classify_regime_simple()`
2. Lower `high_vol` threshold from `atr_ratio > 1.5` to `atr_ratio > 1.25`
3. Make `trend_down` detection less strict (remove `ema20_slope` requirement or fix it)
4. Add fallback: if `change_pct <= -0.05` and `slope20 < 0`, classify as `trend_down`

**Files:**
- `engine_alpha/core/regime.py` - `classify_regime_simple()` function

### Fix #2: Lower Entry Thresholds ✅ MEDIUM PRIORITY

**Goal:** Make thresholds more achievable while maintaining quality

**Changes:**
1. Lower `trend_down` threshold from 0.52 to 0.48
2. Lower `high_vol` threshold from 0.40 to 0.38
3. Keep `chop` at 0.75 (doesn't matter since it's blocked)

**Files:**
- `config/entry_thresholds.json`

### Fix #3: Adjust Neutral Zone ✅ LOW PRIORITY

**Goal:** Reduce false neutralizations

**Changes:**
1. Lower neutral zone from 0.30 to 0.25
2. OR make neutral zone regime-aware (stricter in chop, looser in trends)

**Files:**
- `engine_alpha/loop/autonomous_trader.py` - `NEUTRAL_THRESHOLD` constant

### Fix #4: Allow Chop Entries (Optional) ⚠️ NOT RECOMMENDED

**Goal:** Allow entries in chop with very high threshold

**Changes:**
1. Modify `regime_allows_entry()` to allow `chop` if confidence >= 0.75
2. This defeats the purpose of regime gating

**Files:**
- `engine_alpha/loop/autonomous_trader.py` - `regime_allows_entry()` function

---

## 📊 Expected Impact

### After Fix #1 (Regime Classifier):
- **Before:** 0% `trend_down`, 0% `high_vol`, 100% `chop`
- **After:** ~30-40% `trend_down`, ~10-15% `high_vol`, ~45-60% `chop`
- **Trades:** Should see entries in `trend_down` and `high_vol` periods

### After Fix #2 (Lower Thresholds):
- **Before:** Only 1/21 bars had conf >= 0.52
- **After:** ~5-8/21 bars should have conf >= 0.48
- **Trades:** More entries in allowed regimes

### After Fix #3 (Neutral Zone):
- **Before:** 52.4% neutralized
- **After:** ~30-35% neutralized
- **Trades:** More bars pass neutral zone check

### Combined Impact:
- **Expected trades:** 5-10 entries per 100 bars (vs 0 currently)
- **Quality:** Still high (only strong signals in allowed regimes)

---

## 🚀 Implementation Priority

1. ✅ **Fix #1** - Regime Classifier (CRITICAL - enables trades)
2. ✅ **Fix #2** - Lower Thresholds (HIGH - increases trade count)
3. ⚠️ **Fix #3** - Neutral Zone (MEDIUM - nice to have)
4. ❌ **Fix #4** - Allow Chop (NOT RECOMMENDED)

---

## 📝 Verification Steps

After fixes:

1. Run diagnostic on same period:
   ```bash
   python3 -m tools.diagnose_zero_trades --timestamp 2022-04-15T12:00:00Z --csv data/ohlcv/ETHUSDT_1h_merged.csv --sample 100
   ```

2. Verify regime distribution:
   - Should see `trend_down` and `high_vol` classifications
   - `chop` should be < 80%

3. Run backtest:
   ```bash
   python3 -m tools.backtest_harness --symbol ETHUSDT --timeframe 1h --start 2022-04-01T00:00:00Z --end 2022-04-30T00:00:00Z
   ```

4. Verify trades:
   - Should see > 0 opens
   - Should see > 0 closes
   - PF should be meaningful

---

**End of Analysis**


