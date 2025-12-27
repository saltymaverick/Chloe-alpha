# Chloe Alpha Auditor Report

**Date:** 2024-11-23  
**Role:** Auditor  
**Scope:** Live/Paper Health, Backtest Windows, Scratch vs Meaningful Trades

## Executive Summary

**Status: ❌ NOT READY FOR LIVE TRADING**

Chloe has **zero meaningful trades** in live/paper mode and **zero meaningful trades** in recent backtests. The system is structurally sound but **not trading** due to regime gate restrictions and potentially conservative thresholds.

---

## 1. LIVE / PAPER STATE

### Current Status

```
Trades (open/close): 0 / 0
Meaningful closes: 0
PF (meaningful only): 0.000
REC: REVIEW | Band: None | Mult: 1.0
```

### Analysis

- **Meaningful closes:** 0 (TP/SL, |pct| >= 0.0005)
- **PF overall:** N/A (no trades)
- **PF by regime:** No data
- **Scratch ratio:** 0.00 (no trades to classify)

### Verdict

**🚫 DO NOT TRADE**

**Reasoning:**
- Zero trading history means no edge validation
- Cannot assess risk/reward without trade data
- System is structurally sound but not firing trades

**Recommendation:**
- Run backtests with `BACKTEST_FREE_REGIME=1` to allow all regimes
- Analyze why trades aren't opening (regime gate? thresholds? confidence?)
- Once backtests show meaningful trades with PF > 1.1, consider paper trading

---

## 2. BACKTEST WINDOWS

### Recent Backtest Results

#### Run 1: ETHUSDT_1h_20251123T053621Z
- **Period:** 2022-04-01 to 2022-06-30 (trend_down window)
- **Bars processed:** 1,958
- **Closes:** 128
- **Meaningful closes:** **0** (all scratches or below threshold)
- **PF:** 0.000
- **Equity change:** -7.89% (from $10,000 to $9,211)
- **Issue:** 128 closes but 0 meaningful - all scratches or exits with tiny pct

#### Run 2-5: Multiple runs
- **Closes:** 0 (no trades opened)
- **PF:** 0.000
- **Equity change:** 0.00%
- **Issue:** Regime gate blocking entries (all regimes classified as `chop`?)

### Analysis

**Key Findings:**
1. **Regime Classification Issue:** Most backtests show 0 trades, suggesting:
   - Regime classifier is too conservative (everything = `chop`)
   - Regime gate blocks `chop` entries (correct behavior)
   - Need `BACKTEST_FREE_REGIME=1` to test all regimes

2. **Scratch Trade Problem:** The one run with 128 closes shows:
   - All closes are scratches (|pct| < 0.0005) or non-TP/SL exits
   - Equity declined -7.89% despite no "meaningful" trades
   - Suggests many micro-trades with fees/slippage eating equity

3. **No Edge Demonstrated:** Zero meaningful trades means:
   - Cannot assess if Chloe has edge in `trend_down` or `high_vol`
   - Cannot tune thresholds without trade data
   - Cannot validate exit logic (TP/SL effectiveness)

---

## 3. SCRATCH VS MEANINGFUL

### Quantification

**Live/Paper:**
- Total closes: 0
- Scratch closes: 0
- Meaningful closes: 0
- Scratch ratio: N/A

**Backtest (Run 1):**
- Total closes: 128
- Scratch closes: ~128 (all below threshold or non-TP/SL)
- Meaningful closes: 0
- Scratch ratio: ~100%

### Analysis

**Problem:** Chloe is either:
1. **Not trading at all** (regime gate blocking)
2. **Trading but only scratches** (exits firing too early, or entries in wrong regimes)

**Root Cause Hypothesis:**
- Regime classifier labels most periods as `chop`
- Regime gate correctly blocks `chop` entries (LIVE/PAPER behavior)
- When trades do open (backtest with free regime?), exits fire too early
- Result: Many micro-trades with tiny pct, all classified as scratches

**Impact:**
- Fees/slippage accumulate even on scratches
- Equity declines despite "no meaningful trades"
- Cannot assess true edge without meaningful trade data

---

## 4. RECOMMENDATIONS

### Structural Safety ✅

**Is Chloe structurally safe?**
- ✅ Yes - unified code path, no divergent logic
- ✅ Regime gate correctly blocks `chop`/`trend_up` in LIVE/PAPER
- ✅ Exit logic consistent across live/backtest
- ✅ Scratch trade classification working correctly

**Issues Found:**
- ⚠️ Bug: `bucket_debug` not initialized in Phase 54 section (FIXED)
- ⚠️ Regime classifier may be too conservative (needs investigation)

### Demonstrable Edge ❌

**Does Chloe have demonstrable edge in trend_down/high_vol?**
- ❌ **NO** - zero meaningful trades to assess
- Cannot determine edge without trade data
- Need backtests with `BACKTEST_FREE_REGIME=1` to generate trades

### Regime Recommendations

**Which regimes should be disabled?**
- ✅ **Current behavior is correct:**
  - LIVE/PAPER: Only `trend_down` and `high_vol` allowed (correct)
  - `chop` and `trend_up` blocked (correct - no edge demonstrated)
- ⚠️ **Issue:** Regime classifier may be labeling everything as `chop`
  - Need to investigate regime classification thresholds
  - Consider running `tools/signal_return_analyzer` to see regime distribution

---

## Prioritized Action Items

### 🔴 CRITICAL (Do First)

1. **Fix Regime Classification**
   - Run backtest with `BACKTEST_FREE_REGIME=1` to bypass regime gate
   - Analyze regime distribution: Are we getting `trend_down`/`high_vol`?
   - If everything is `chop`, adjust regime classifier thresholds

2. **Generate Meaningful Trades**
   - Run backtest with `BACKTEST_FREE_REGIME=1` on known trend period
   - Target: 20+ meaningful closes with PF > 1.1
   - If still 0 meaningful trades, investigate exit logic (TP/SL thresholds)

3. **Investigate Scratch Trade Problem**
   - Why are 128 closes all scratches?
   - Are exits firing too early (decay/drop)?
   - Are entries happening at wrong times?
   - Check exit thresholds: `tp_conf`, `sl_conf`, `decay_bars`

### 🟡 HIGH PRIORITY (Do Next)

4. **Threshold Tuning**
   - Once meaningful trades exist, run `tools/signal_return_analyzer`
   - Use `tools/gpt_threshold_tuner` to optimize entry thresholds
   - Focus on `trend_down` and `high_vol` regimes

5. **Exit Logic Review**
   - Analyze why trades exit as scratches
   - Consider adjusting TP/SL thresholds
   - Review `decay` and `drop` exit logic

### 🟢 MEDIUM PRIORITY (Monitor)

6. **Live/Paper Monitoring**
   - Once backtests show edge, enable paper trading
   - Monitor for 20+ meaningful closes
   - Only enable LIVE after PF > 1.1 in paper

---

## Conclusion

Chloe is **structurally sound** but **not trading**. The system needs:

1. **Regime classification fix** - likely too conservative
2. **Meaningful trade generation** - need 20+ closes to assess edge
3. **Exit logic review** - prevent scratch trade churn

**Current Status:** 🚫 **DO NOT TRADE** - insufficient data to assess edge.

**Next Steps:** Run backtests with `BACKTEST_FREE_REGIME=1` to generate trades, then analyze regime distribution and exit behavior.


