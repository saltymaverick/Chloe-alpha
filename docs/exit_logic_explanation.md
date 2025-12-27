# Exit Logic Explanation - Plain English

## When a Live PAPER Trade OPENS

A trade opens in `trend_down` or `high_vol` when:

1. **Regime gate passes:** Current regime is `trend_down` or `high_vol` (not `chop` or `trend_up`)
2. **Confidence threshold passes:** `effective_final_conf >= entry_min_conf`
   - `trend_down`: 0.52 (from `config/entry_thresholds.json`)
   - `high_vol`: 0.58 (from `config/entry_thresholds.json`)
3. **Direction is non-zero:** `effective_final_dir != 0` (signal is not neutralized)
4. **Guardrails pass:** 
   - No cooldown active
   - No cluster of recent SL/drop exits
   - Position sizing allows the trade

## When a Live PAPER Trade CLOSES

### TP (Take Profit)
- **Condition:** Signal is still in the **same direction** as the position AND `final_conf >= take_profit_conf`
- **Threshold:** 0.75 (default), 0.60 in `chop` regime
- **Min-hold:** Must wait 4 bars (PAPER) before TP can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG and conf rises to 0.75+ → TP fires

### SL (Stop Loss)
- **Condition:** Signal **flipped direction** (opposite to position) AND `final_conf >= stop_loss_conf`
- **Threshold:** 0.12 (default), 0.50 in `chop` regime
- **Min-hold:** Can fire immediately (critical exit, bypasses min-hold)
- **Example:** Opened LONG at conf=0.55, signal flips to SHORT with conf=0.12+ → SL fires

### Drop (Signal Drop)
- **Condition:** `final_conf < exit_min_conf` (signal confidence dropped too low)
- **Threshold:** 0.30 (default)
- **Min-hold:** Must wait 4 bars (PAPER) before drop can fire
- **Example:** Opened LONG at conf=0.55, signal stays LONG but conf drops below 0.30 → Drop fires

### Decay (Time Decay)
- **Condition:** `bars_open >= decay_bars` (trade held too long)
- **Threshold:** 8 bars (from `config/gates.yaml`, but code default is 8)
- **Min-hold:** Independent (can fire regardless of min-hold)
- **Example:** Opened LONG, held for 8+ bars without TP/SL/Drop firing → Decay fires

## Problem: Too Many Drop/Decay Exits

**Current behavior:**
- Many trades exit via `drop` (conf < 0.30) or `decay` (8 bars) before reaching TP (conf >= 0.75) or SL
- This creates scratch trades (tiny pct) instead of meaningful TP/SL outcomes

**Root causes:**
1. **TP threshold too high (0.75):** Trades rarely reach this confidence level before drop/decay fires
2. **Drop threshold too low (0.30):** Fires too easily, cutting trades short
3. **Decay too short (8 bars):** Not enough time for trades to develop and reach TP/SL


