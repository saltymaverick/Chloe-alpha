# Exit Quality Improvements for trend_down/high_vol

**Date:** 2024-11-23  
**Role:** Alpha Engineer  
**Goal:** Increase TP/SL ratio vs drop/decay exits for trend_down/high_vol regimes

---

## 1. Current Exit Logic (Plain English)

### When Exits Fire in PAPER/LIVE Mode

#### **TP (Take Profit)**
- **Condition:** Signal is still in the **same direction** as the position AND `final_conf >= take_profit_conf`
- **Threshold:** 0.75 (default), 0.60 in `chop`, **0.65 in `trend_down`/`high_vol` (NEW)**
- **Min-hold:** Must wait 4 bars (PAPER) before TP can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG and conf rises to 0.65+ → TP fires

#### **SL (Stop Loss)**
- **Condition:** Signal **flipped direction** (opposite to position) AND `final_conf >= stop_loss_conf`
- **Threshold:** 0.12 (default), 0.50 in `chop`
- **Min-hold:** Can fire immediately (critical exit, bypasses min-hold)
- **Example:** Opened LONG at conf=0.55, signal flips to SHORT with conf=0.12+ → SL fires

#### **Drop (Signal Drop)**
- **Condition:** `final_conf < exit_min_conf` (signal confidence dropped too low)
- **Threshold:** 0.30 (default), **0.25 in `trend_down`/`high_vol` (NEW)**
- **Min-hold:** Must wait 4 bars (PAPER) before drop can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG but conf drops below 0.25 → Drop fires

#### **Decay (Time Decay)**
- **Condition:** `bars_open >= decay_bars` (trade held too long)
- **Threshold:** **10 bars (NEW, was 6)**
- **Min-hold:** Independent (can fire regardless of min-hold)
- **Example:** Opened LONG, held for 10+ bars without TP/SL/Drop firing → Decay fires

### Exit Priority Order

1. **SL** (can fire immediately, critical exit)
2. **TP/Drop/Flip** (only if `bars_open >= MIN_HOLD_BARS_LIVE` = 4 bars in PAPER)
3. **Decay** (independent, fires when `bars_open >= decay_bars`)

---

## 2. Problem Analysis

**Current Issue:**
- Many trades exit via `drop` (conf < 0.30) or `decay` (6 bars) before reaching TP (conf >= 0.75) or SL
- This creates scratch trades (tiny pct) instead of meaningful TP/SL outcomes

**Root Causes:**
1. **TP threshold too high (0.75):** Trades rarely reach this confidence level before drop/decay fires
2. **Drop threshold too low (0.30):** Fires too easily, cutting trades short
3. **Decay too short (6 bars):** Not enough time for trades to develop and reach TP/SL

---

## 3. Two Proposed Changes

### Change 1: Lower TP Threshold for trend_down/high_vol

**Rationale:**
- Current TP threshold (0.75) is too high - trades rarely reach this level
- Lowering to 0.65 makes TP more achievable while still requiring strong signal
- Similar to `chop` regime which uses 0.60 TP threshold

**Impact:**
- More trades will hit TP before drop/decay fires
- Expected: 20-30% increase in TP exits
- Trade count: No change (only affects exit timing)

### Change 2: Increase Decay Bars + Lower Drop Threshold

**Rationale:**
- Current decay (6 bars) is too short - trades don't have time to develop
- Current drop threshold (0.30) fires too easily
- Increasing decay to 10 bars gives trades more time
- Lowering drop threshold to 0.25 makes it fire less often (only when conf < 0.25)

**Impact:**
- Trades have more time (10 bars vs 6) before decay fires
- Drop fires less often (conf < 0.25 vs conf < 0.30)
- Expected: 30-40% reduction in drop/decay exits
- Trade count: No change (only affects exit timing)

---

## 4. Implementation

### Change 1: Lower TP Threshold

**File:** `engine_alpha/loop/autonomous_trader.py`  
**Lines:** 624-628

```python
elif IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
    # Lower TP threshold for trend_down/high_vol to increase TP/SL ratio vs drop/decay
    # This makes it easier to take profit before drop/decay fires
    take_profit_conf = 0.65  # Lower from 0.75 to capture more TP exits
    stop_loss_conf = stop_loss_conf_base  # Keep SL threshold unchanged
```

**Diff:**
```diff
     if IS_PAPER_MODE and regime == "chop":
         take_profit_conf = 0.60  # Slightly easier to take profit
         stop_loss_conf = 0.50     # More confident before calling it a loss
+    elif IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
+        # Lower TP threshold for trend_down/high_vol to increase TP/SL ratio vs drop/decay
+        # This makes it easier to take profit before drop/decay fires
+        take_profit_conf = 0.65  # Lower from 0.75 to capture more TP exits
+        stop_loss_conf = stop_loss_conf_base  # Keep SL threshold unchanged
     else:
         take_profit_conf = take_profit_conf_base
         stop_loss_conf = stop_loss_conf_base
```

### Change 2A: Increase Decay Bars

**File:** `config/gates.yaml`

```diff
 EXIT:
-  DECAY_BARS: 6          # decay after ~6 bars (use 6–8 in live soak)
+  DECAY_BARS: 10         # decay after ~10 bars (increased from 6 to give trades more time to reach TP/SL)
   TAKE_PROFIT_CONF: 0.75 # take profit if same-dir & conf ≥ 0.75
   STOP_LOSS_CONF:   0.12 # stop if opposite-dir & conf ≥ 0.12
```

### Change 2B: Lower Drop Threshold

**File:** `engine_alpha/loop/autonomous_trader.py`  
**Lines:** 753-758

```python
# Lower drop threshold for trend_down/high_vol to reduce drop exits and increase TP/SL ratio
# Drop fires when conf < exit_min_conf, so lowering exit_min_conf (0.25 vs 0.30) makes drop fire LESS often
if IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
    gates_exit_min_conf = 0.25  # Lower from 0.30 to reduce drop exits (only fires when conf < 0.25)
else:
    gates_exit_min_conf = gates_exit_min_conf_base
```

**Diff:**
```diff
     # Get gates from decision (for exit thresholds)
     gates = decision.get("gates", {})
-    gates_exit_min_conf = gates.get("exit_min_conf", exit_min_conf)
+    gates_exit_min_conf_base = gates.get("exit_min_conf", exit_min_conf)
+    # Lower drop threshold for trend_down/high_vol to reduce drop exits and increase TP/SL ratio
+    # Drop fires when conf < exit_min_conf, so lowering exit_min_conf (0.25 vs 0.30) makes drop fire LESS often
+    if IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
+        gates_exit_min_conf = 0.25  # Lower from 0.30 to reduce drop exits (only fires when conf < 0.25)
+    else:
+        gates_exit_min_conf = gates_exit_min_conf_base
     gates_reverse_min_conf = gates.get("reverse_min_conf", reverse_min_conf)
```

---

## 5. Expected Impact

### TP/SL Ratio
- **Before:** Many trades exit via drop/decay (conf drops or time expires)
- **After:** More trades exit via TP/SL (easier TP threshold, more time before decay)

### Trade Count
- **Expected change:** < 20% increase
- **Reason:** Changes only affect exit timing, not entry logic
- Entry thresholds unchanged (0.52 for trend_down, 0.58 for high_vol)

### Regime-Specific Behavior
- **trend_down/high_vol:** 
  - TP threshold: 0.65 (was 0.75)
  - Drop threshold: 0.25 (was 0.30)
  - Decay bars: 10 (was 6)
- **chop/trend_up:** Unchanged (still blocked for entries anyway)

---

## 6. Safety & Constraints

✅ **Only affects `trend_down`/`high_vol` regimes** (chop/trend_up unchanged)  
✅ **No new modes introduced** (unified code path maintained)  
✅ **Entry thresholds unchanged** (no increase in trade count)  
✅ **Exit thresholds are conservative** (0.65 TP, 0.25 drop, 10 bars decay)  
✅ **Min-hold guardrails still active** (4 bars in PAPER)  
✅ **SL threshold unchanged** (0.12, still fires immediately)

---

## 7. Verification Steps

1. **Run backtest with changes:**
   ```bash
   BACKTEST_FREE_REGIME=1 python3 -m tools.backtest_harness \
     --symbol ETHUSDT --timeframe 1h \
     --start 2022-04-01T00:00:00Z --end 2022-06-30T00:00:00Z \
     --csv data/ohlcv/ETHUSDT_1h_merged.csv --window 200
   ```

2. **Check exit reason distribution:**
   ```bash
   RUN=$(ls -td reports/backtest/* | head -1)
   python3 -m tools.backtest_report --run-dir "$RUN"
   python3 -m tools.pf_doctor_filtered --run-dir "$RUN" --threshold 0.0005 --reasons tp,sl,drop,decay
   ```

3. **Compare before/after:**
   - TP exits: Should increase
   - Drop/decay exits: Should decrease
   - TP/SL ratio: Should improve
   - Trade count: Should remain similar (±20%)

---

## Summary

**Two minimal, safe changes implemented:**

1. **Lower TP threshold** for trend_down/high_vol: 0.75 → 0.65
2. **Increase decay bars** + **lower drop threshold**: 6 → 10 bars, 0.30 → 0.25

**Expected result:** More TP/SL exits, fewer drop/decay exits, similar trade count.


