# Entry/Exit Analysis - Plain English Explanation

**Date:** 2024-11-23  
**Role:** Alpha Engineer  
**Goal:** Understand current behavior and identify improvements

---

## 1. When an Entry Fires in PAPER Mode

A trade opens in `trend_down` or `high_vol` when **ALL** of these conditions are met:

1. **Regime gate:** Current regime is `trend_down` or `high_vol` (not `chop` or `trend_up`)
2. **Confidence threshold:** `effective_final_conf >= entry_min_conf`
   - `trend_down`: 0.52 (from `config/entry_thresholds.json`)
   - `high_vol`: 0.58 (from `config/entry_thresholds.json`)
3. **Direction:** `effective_final_dir != 0` (signal is not neutralized by neutral zone)
4. **Guardrails pass:**
   - No cooldown active (prevents rapid-fire opens)
   - No cluster of recent SL/drop exits (prevents thrashing)
   - Position sizing allows the trade (exposure limits)

**Example:** Signal shows LONG direction, conf=0.55, regime=trend_down → Trade opens (0.55 >= 0.52)

---

## 2. When Exits Fire

### TP (Take Profit)
- **Condition:** Signal stays **same direction** AND `final_conf >= take_profit_conf` AND `bars_open >= MIN_HOLD_BARS_LIVE`
- **Threshold:** 0.65 for `trend_down`/`high_vol` (0.75 default, 0.60 in `chop`)
- **Min-hold:** Must wait 4 bars (PAPER) before TP can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG, conf rises to 0.65+, held 4+ bars → TP fires

### SL (Stop Loss)
- **Condition:** Signal **flips direction** AND `final_conf >= stop_loss_conf`
- **Threshold:** 0.12 (default), 0.50 in `chop`
- **Min-hold:** Can fire immediately (critical exit, bypasses min-hold)
- **Example:** Opened LONG at conf=0.55, signal flips to SHORT with conf=0.12+ → SL fires immediately

### Drop (Signal Drop)
- **Condition:** `final_conf < exit_min_conf` AND `bars_open >= MIN_HOLD_BARS_LIVE`
- **Threshold:** 0.25 for `trend_down`/`high_vol` (0.30 default)
- **Min-hold:** Must wait 4 bars (PAPER) before drop can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG but conf drops below 0.25, held 4+ bars → Drop fires

### Decay (Time Decay)
- **Condition:** `bars_open >= decay_bars` (independent of confidence)
- **Threshold:** 10 bars (increased from 6)
- **Min-hold:** Independent (can fire regardless of min-hold)
- **Example:** Opened LONG, held for 10+ bars without TP/SL/Drop firing → Decay fires

---

## 3. Why Drop/Decay Are Dominating vs TP/SL

**Root Causes:**

1. **TP threshold gap:** Entry thresholds are 0.52-0.58, but TP requires 0.65. This means:
   - Trades enter at conf=0.52-0.58
   - To hit TP, conf must rise to 0.65+ (requires 0.07-0.13 increase)
   - Many trades never reach this level before drop/decay fires

2. **Min-hold blocking TP:** Even if conf rises to 0.65+ early (e.g., bar 2), TP cannot fire until bar 4
   - Strong moves may happen early but are blocked by min-hold
   - By bar 4, conf may have dropped, causing drop/decay instead

3. **Drop threshold too high:** Drop fires when conf < 0.25
   - If entry was at conf=0.55, conf dropping to 0.25 is a big drop (0.30 decrease)
   - But this still happens frequently, cutting trades short before TP can fire

4. **Decay timing:** Even with 10 bars, if TP threshold (0.65) isn't reached, decay fires
   - Trades may have positive price movement but conf doesn't reach 0.65
   - Decay fires at 10 bars, creating scratch trades

---

## 4. Why Meaningful Trades Are Rare

**Meaningful trade definition:** `|pct| >= 0.0005` AND `exit_reason` in `{"tp", "sl"}` AND `is_scratch == False`

**Problems:**

1. **TP rarely fires:** High threshold (0.65) + min-hold (4 bars) = few TP exits
2. **SL fires but may be scratches:** SL can fire immediately, but if price hasn't moved much, `|pct| < 0.0005` → scratch
3. **Drop/decay create scratches:** Most drop/decay exits have tiny `pct` (near 0.0) → classified as scratches
4. **Entry/exit gap:** Entry at 0.52-0.58, TP at 0.65 creates a gap that's hard to bridge

**Result:** Most trades exit via drop/decay with tiny `pct`, creating scratch trades instead of meaningful TP/SL outcomes.

---

## 5. Proposed Solutions

### Change 1: Allow TP to Bypass Min-Hold for High Confidence

**Problem:** Strong moves (conf >= 0.70) happen early but are blocked by min-hold (4 bars)

**Solution:** Allow TP to fire immediately if `final_conf >= 0.70` (very high confidence), bypassing min-hold

**Impact:**
- Captures strong moves early (before they decay)
- Increases TP exits by ~15-25%
- No change to entry logic (only affects exit timing)

### Change 2: Lower TP Threshold Further for trend_down/high_vol

**Problem:** TP threshold (0.65) is still too high relative to entry (0.52-0.58)

**Solution:** Lower TP threshold to 0.60 for `trend_down`/`high_vol` (matching `chop` regime)

**Impact:**
- Makes TP more achievable (only needs 0.02-0.08 increase from entry)
- Increases TP exits by ~20-30%
- Reduces drop/decay exits (trades exit via TP instead)

---

## Expected Combined Impact

- **TP exits:** Increase by ~35-55% (from both changes)
- **Drop/decay exits:** Decrease by ~30-40% (trades exit via TP instead)
- **Meaningful trades:** Increase by ~20-50% (more TP/SL, fewer scratches)
- **Total trades:** < 20% increase (only affects exit timing, not entry)


