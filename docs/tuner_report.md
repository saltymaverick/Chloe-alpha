# Chloe Alpha Tuner Report

**Date:** 2024-11-23  
**Role:** Tuner  
**Scope:** Threshold Tuning Based on Signal Return Analysis

## Executive Summary

Analyzed confidence × regime performance data and improved the GPT threshold tuner to intelligently place thresholds **toward good bands** rather than blindly pushing them up.

---

## 1. DATA ANALYSIS

### Confidence Band Performance by Regime

#### **trend_down**
- ✅ **Good bands (PF≥1.2, n≥100):** 1
  - `[0.65-0.70)`: PF=1.272, n=499
- ⚠️ **Meh bands (1.0≤PF<1.2):** 6
- ❌ **Bad bands (PF<1.0):** 7
- **Current threshold:** 0.52
- **Recommendation:** Set to **0.63** (just below 0.65, the lower edge of the good band)

#### **high_vol**
- ✅ **Good bands (PF≥1.2, n≥100):** 2
  - `[0.40-0.45)`: PF=1.308, n=387 (best sample size)
  - `[0.60-0.65)`: PF=1.334, n=265 (best PF)
- ⚠️ **Meh bands (1.0≤PF<1.2):** 3
- ❌ **Bad bands (PF<1.0):** 7
- **Current threshold:** 0.58
- **Recommendation:** Set to **0.38** (just below 0.40, capturing the first good band with more samples)

#### **trend_up**
- ✅ **Good bands (PF≥1.2, n≥100):** 3
  - `[0.35-0.40)`: PF=1.235, n=737
  - `[0.45-0.50)`: PF=1.292, n=554
  - `[0.55-0.60)`: PF=1.240, n=585
- ⚠️ **Meh bands (1.0≤PF<1.2):** 4
- ❌ **Bad bands (PF<1.0):** 7
- **Current threshold:** 0.65
- **Recommendation:** Keep at **0.65+** (trend_up is blocked for live trading anyway, but if enabled, would set to 0.33)

#### **chop**
- ⚠️ **Meh bands (1.0≤PF<1.2):** 5
  - Best: `[0.45-0.50)`: PF=1.141, n=1259
- ❌ **Bad bands (PF<1.0):** 7
- **Current threshold:** 0.75
- **Recommendation:** Keep at **0.75+** (chop is blocked for live trading anyway)

---

## 2. THRESHOLD RULES DESIGNED

### Rule 1: Good Bands (PF ≥ 1.2, n ≥ 100)
- **Action:** Set threshold to `lower_edge - 0.02`
- **Rationale:** Captures the good band while allowing margin for rounding
- **Example:** Good band `[0.65-0.70)` → threshold `0.63`

### Rule 2: Only Meh Bands (1.0 ≤ PF < 1.2, n ≥ 100)
- **Action:** Keep current threshold (unless clearly wrong)
- **Rationale:** Meh bands are acceptable but not great; don't change unless necessary

### Rule 3: All Bad Bands (PF < 1.0, n ≥ 100)
- **Action:** Raise threshold to 0.75+ (avoid trading)
- **Rationale:** No edge demonstrated; should be disabled anyway

### Rule 4: Low Sample Size (n < 100)
- **Action:** Ignore unless overwhelming edge (PF > 1.5)
- **Rationale:** Unreliable without sufficient samples

### Rule 5: Safety Constraints
- **Hard clamp:** [0.35, 0.85]
- **trend_up/chop:** Keep high (≥0.65) unless overwhelming edge
- **Current gates:** Only `trend_down` and `high_vol` enabled for live

---

## 3. GPT PROMPT IMPROVEMENTS

### What Changed

**Before:**
- Generic instruction: "maximize profitable trades while filtering out unprofitable ones"
- No specific guidance on threshold placement
- GPT tended to push thresholds up (more conservative)

**After:**
- **Explicit threshold placement rules:**
  - Good bands → set to `lower_edge - 0.02`
  - Meh bands → keep current (unless wrong)
  - Bad bands → raise to 0.75+
- **Band classification in prompt:**
  - GOOD bands clearly marked with suggested threshold
  - MEH and BAD bands shown for context
- **Philosophy shift:**
  - "DO NOT blindly push thresholds up"
  - "DO push thresholds TOWARD good bands"
  - Example: If good band is `[0.40-0.45)`, set threshold to `0.38` (not `0.50+`)

### Why This Makes Sense

1. **Data-driven:** Thresholds are placed based on where edge actually exists
2. **Balanced:** Captures good bands while filtering bad bands
3. **Not overly conservative:** Doesn't push thresholds above good bands unnecessarily
4. **Sample-size aware:** Prioritizes bands with n ≥ 100

---

## 4. EXPECTED THRESHOLD RECOMMENDATIONS

Based on the analysis, GPT should recommend:

```json
{
  "trend_down": {"enabled": true,  "entry_min_conf": 0.63},
  "high_vol":   {"enabled": true,  "entry_min_conf": 0.38},
  "trend_up":   {"enabled": false, "entry_min_conf": 0.65},
  "chop":       {"enabled": false, "entry_min_conf": 0.75}
}
```

**Rationale:**
- **trend_down:** 0.63 captures the good band `[0.65-0.70)` (PF=1.272)
- **high_vol:** 0.38 captures the good band `[0.40-0.45)` (PF=1.308, n=387)
- **trend_up:** 0.65 kept high (blocked anyway)
- **chop:** 0.75 kept high (blocked anyway)

---

## 5. USAGE INSTRUCTIONS

### Step 1: Re-run Analyzer (if needed)

```bash
python3 -m tools.signal_return_analyzer \
  --symbol ETHUSDT \
  --timeframe 1h \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --window 200 \
  --step-horizon 1 \
  --output reports/analysis/conf_ret_summary.json
```

**When to re-run:**
- After significant code changes (regime classifier, confidence engine)
- After collecting new historical data
- Periodically (e.g., monthly) to refresh analysis

### Step 2: Run GPT Tuner (Dry Run)

```bash
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json \
  --model gpt-4o
```

**What it does:**
- Loads analysis summary
- Builds improved GPT prompt with band classification
- Calls GPT API for recommendations
- Prints comparison table (old vs new thresholds)
- **Does NOT apply changes** (dry run)

### Step 3: Inspect Recommendations

Review the output table:
```
Regime       Enabled  OldThr   NewThr
----------------------------------------
trend_down   true     0.52     0.63
high_vol     true     0.58     0.38
trend_up     false    0.65     0.65
chop         false    0.75     0.75
```

**Verify:**
- Do thresholds align with good bands?
- Are they within [0.35, 0.85]?
- Do they make sense given the data?

### Step 4: Apply Recommendations

```bash
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json \
  --model gpt-4o \
  --apply
```

**What it does:**
- Same as Step 2, but writes to `config/entry_thresholds.json`
- Preserves other fields in config file
- Hard clamps thresholds to [0.35, 0.85]

### Step 5: Verify with Backtest

```bash
# Run backtest with new thresholds
BACKTEST_FREE_REGIME=1 python3 -m tools.backtest_harness \
  --symbol ETHUSDT \
  --timeframe 1h \
  --start 2022-04-01T00:00:00Z \
  --end 2022-06-30T00:00:00Z \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --window 200

# Check results
RUN=$(ls -td reports/backtest/* | head -1)
python3 -m tools.backtest_report --run-dir "$RUN"
python3 -m tools.pf_doctor_filtered --run-dir "$RUN" --threshold 0.0005 --reasons tp,sl
```

**Success criteria:**
- 20+ meaningful closes
- PF > 1.1
- Regime distribution makes sense

---

## 6. SAFETY MEASURES

### Hard Clamps
- All thresholds clamped to [0.35, 0.85]
- Prevents extreme values

### Preserve Config
- Only updates threshold fields
- Preserves other config fields

### Regime Gates
- `trend_up` and `chop` kept high (≥0.65) unless overwhelming edge
- Currently blocked for live trading anyway

### Validation
- GPT response validated for correct format
- Thresholds validated for range
- Warnings printed for invalid values

---

## 7. RERUN TUNING LOOP

### When to Rerun

1. **After code changes:**
   - Regime classifier updates
   - Confidence engine changes
   - Signal processing modifications

2. **After new data:**
   - Extended historical period
   - New market conditions

3. **Periodically:**
   - Monthly refresh
   - Quarterly review

### Safe Rerun Process

```bash
# 1. Backup current thresholds
cp config/entry_thresholds.json config/entry_thresholds.json.backup

# 2. Re-run analyzer
python3 -m tools.signal_return_analyzer ...

# 3. Dry run tuner
python3 -m tools.gpt_threshold_tuner --summary reports/analysis/conf_ret_summary.json

# 4. Review recommendations
# (manual review of output)

# 5. Apply if good
python3 -m tools.gpt_threshold_tuner --summary reports/analysis/conf_ret_summary.json --apply

# 6. Verify with backtest
BACKTEST_FREE_REGIME=1 python3 -m tools.backtest_harness ...

# 7. Rollback if needed
cp config/entry_thresholds.json.backup config/entry_thresholds.json
```

---

## Conclusion

The GPT threshold tuner has been improved to:
- **Place thresholds intelligently** toward good bands (not blindly push up)
- **Classify bands** by performance (GOOD/MEH/BAD)
- **Provide explicit guidance** on threshold placement rules
- **Maintain safety** with hard clamps and validation

**Expected impact:**
- `trend_down`: Threshold lowered from 0.52 → 0.63 (captures good band)
- `high_vol`: Threshold lowered from 0.58 → 0.38 (captures good band)
- More trades in profitable confidence ranges
- Better PF by regime

**Next steps:**
1. Run GPT tuner to get recommendations
2. Apply if recommendations make sense
3. Verify with backtests
4. Monitor live/paper performance


