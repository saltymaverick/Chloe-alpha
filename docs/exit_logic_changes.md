# Exit Logic Changes - Increase TP/SL Ratio

**Date:** 2024-11-23  
**Role:** Alpha Engineer  
**Goal:** Increase TP/SL ratio vs drop/decay exits for trend_down/high_vol regimes

---

## Plain English Explanation

### When a Live PAPER Trade OPENS

A trade opens in `trend_down` or `high_vol` when:

1. **Regime gate passes:** Current regime is `trend_down` or `high_vol` (not `chop` or `trend_up`)
2. **Confidence threshold passes:** `effective_final_conf >= entry_min_conf`
   - `trend_down`: 0.52 (from `config/entry_thresholds.json`)
   - `high_vol`: 0.58 (from `config/entry_thresholds.json`)
3. **Direction is non-zero:** `effective_final_dir != 0` (signal is not neutralized)
4. **Guardrails pass:** No cooldown, no cluster of recent SL/drop exits, position sizing allows

### When a Live PAPER Trade CLOSES

#### TP (Take Profit)
- **Condition:** Signal is still in the **same direction** as the position AND `final_conf >= take_profit_conf`
- **Threshold:** 
  - **Before:** 0.75 (default)
  - **After:** 0.65 for `trend_down`/`high_vol` (0.75 unchanged for other regimes)
- **Min-hold:** Must wait 4 bars (PAPER) before TP can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG and conf rises to 0.65+ → TP fires

#### SL (Stop Loss)
- **Condition:** Signal **flipped direction** (opposite to position) AND `final_conf >= stop_loss_conf`
- **Threshold:** 0.12 (unchanged)
- **Min-hold:** Can fire immediately (critical exit, bypasses min-hold)
- **Example:** Opened LONG at conf=0.55, signal flips to SHORT with conf=0.12+ → SL fires

#### Drop (Signal Drop)
- **Condition:** `final_conf < exit_min_conf` (signal confidence dropped too low)
- **Threshold:**
  - **Before:** 0.30 (default)
  - **After:** 0.25 for `trend_down`/`high_vol` (0.30 unchanged for other regimes)
- **Min-hold:** Must wait 4 bars (PAPER) before drop can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG but conf drops below 0.25 → Drop fires

#### Decay (Time Decay)
- **Condition:** `bars_open >= decay_bars` (trade held too long)
- **Threshold:**
  - **Before:** 6 bars (from `config/gates.yaml`)
  - **After:** 10 bars (increased to give trades more time to reach TP/SL)
- **Min-hold:** Independent (can fire regardless of min-hold)
- **Example:** Opened LONG, held for 10+ bars without TP/SL/Drop firing → Decay fires

---

## Changes Made

### Change 1: Lower TP Threshold for trend_down/high_vol

**File:** `engine_alpha/loop/autonomous_trader.py` (lines 620-627)

**Before:**
```python
if IS_PAPER_MODE and regime == "chop":
    take_profit_conf = 0.60
    stop_loss_conf = 0.50
else:
    take_profit_conf = take_profit_conf_base  # 0.75
    stop_loss_conf = stop_loss_conf_base
```

**After:**
```python
if IS_PAPER_MODE and regime == "chop":
    take_profit_conf = 0.60
    stop_loss_conf = 0.50
elif IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
    # Lower TP threshold for trend_down/high_vol to increase TP/SL ratio vs drop/decay
    take_profit_conf = 0.65  # Lower from 0.75 to capture more TP exits
    stop_loss_conf = stop_loss_conf_base
else:
    take_profit_conf = take_profit_conf_base
    stop_loss_conf = stop_loss_conf_base
```

**Impact:**
- More trades will hit TP before drop/decay fires
- TP threshold lowered from 0.75 → 0.65 for `trend_down`/`high_vol`
- Expected: 20-30% increase in TP exits

### Change 2: Increase Decay Bars and Lower Drop Threshold

**File 1:** `config/gates.yaml`

**Before:**
```yaml
EXIT:
  DECAY_BARS: 6
```

**After:**
```yaml
EXIT:
  DECAY_BARS: 10  # Increased from 6 to give trades more time to reach TP/SL
```

**File 2:** `engine_alpha/loop/autonomous_trader.py` (lines 750-757)

**Before:**
```python
gates = decision.get("gates", {})
gates_exit_min_conf = gates.get("exit_min_conf", exit_min_conf)  # 0.30
```

**After:**
```python
gates = decision.get("gates", {})
gates_exit_min_conf_base = gates.get("exit_min_conf", exit_min_conf)
# Lower drop threshold for trend_down/high_vol to reduce drop exits
# Drop fires when conf < exit_min_conf, so lowering exit_min_conf (0.25 vs 0.30) makes drop fire LESS often
if IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
    gates_exit_min_conf = 0.25  # Lower from 0.30 to reduce drop exits
else:
    gates_exit_min_conf = gates_exit_min_conf_base
```

**Impact:**
- Trades have more time (10 bars vs 6) before decay fires
- Drop fires less often (conf < 0.25 vs conf < 0.30)
- Expected: 30-40% reduction in drop/decay exits

---

## Expected Impact

### TP/SL Ratio
- **Before:** Many trades exit via drop/decay (conf drops or time expires)
- **After:** More trades exit via TP/SL (easier TP threshold, more time before decay)

### Trade Count
- **Expected increase:** < 20%
- **Reason:** Changes only affect exit timing, not entry logic
- Entry thresholds unchanged (0.52 for trend_down, 0.58 for high_vol)

### Regime-Specific Behavior
- **trend_down/high_vol:** Lower TP (0.65), lower drop (0.25), longer decay (10 bars)
- **chop/trend_up:** Unchanged (still blocked for entries anyway)

---

## Verification Steps

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

---

## Safety

- ✅ Only affects `trend_down`/`high_vol` regimes (chop/trend_up unchanged)
- ✅ No new modes introduced (unified code path maintained)
- ✅ Entry thresholds unchanged (no increase in trade count)
- ✅ Exit thresholds are conservative adjustments (0.65 TP, 0.25 drop, 10 bars decay)
- ✅ Min-hold guardrails still active (4 bars in PAPER)


