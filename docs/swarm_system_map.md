# SWARM System Map - Chloe Trading Pipeline

**Generated:** 2025-11-23  
**Team:** ARCHITECT + QUANT + BACKTESTER + EXECUTION ENGINEER + RISK OFFICER

---

## 🔄 EXECUTION PIPELINE (Single Bar Flow)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA INPUT                                                   │
├─────────────────────────────────────────────────────────────────┤
│ Live:  get_live_ohlcv() → API/exchange                          │
│ Backtest: Mock get_live_ohlcv() → CSV window                    │
│ Output: List[Dict] with {ts, open, high, low, close, volume}    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. REGIME CLASSIFICATION (engine_alpha/core/regime.py)          │
├─────────────────────────────────────────────────────────────────┤
│ Input:  window = rows[-20:] (last 20 bars)                      │
│ Process: classify_regime(window) → classify_regime_simple()     │
│          - Computes slopes (5, 20, 50 bars)                    │
│          - Computes HH/LL counts                                │
│          - Computes ATR14, ATR100, atr_ratio                   │
│          - Computes change_pct over window                      │
│ Output: {"regime": "trend_down"|"high_vol"|"chop"|"trend_up",  │
│          "metrics": {...}}                                      │
│                                                                  │
│ Classification Rules:                                          │
│   - high_vol: atr_pct >= 0.020 OR atr_ratio >= 1.15            │
│   - trend_up: change_pct >= 0.03 AND slope20 > 0 AND hh >= ll │
│   - trend_down: change_pct <= -0.02 AND slope20 < 0 AND ll>=hh │
│   - trend_down (fallback): slope20 < 0 AND ll > hh AND         │
│                            change_pct <= -0.005                  │
│   - chop: default (everything else)                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. SIGNAL PROCESSING (engine_alpha/signals/signal_processor.py)│
├─────────────────────────────────────────────────────────────────┤
│ Input:  symbol, timeframe, limit=200                            │
│ Process: get_signal_vector_live()                                │
│          - Loads signal_registry.json (12 signals)              │
│          - Calls signal_fetchers.* for each signal              │
│          - Normalizes signals to [-1, 1]                        │
│ Output: {"signal_vector": List[float],                          │
│          "raw_registry": Dict, "ts": str}                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. CONFIDENCE AGGREGATION (engine_alpha/core/confidence_engine)│
├─────────────────────────────────────────────────────────────────┤
│ Input:  signal_vector, raw_registry, regime_override            │
│ Process: decide(signal_vector, raw_registry, regime_override)   │
│                                                                  │
│   Step 4a: Map signals → buckets                                │
│            - Ret_G5, MACD_Hist → momentum                       │
│            - RSI_14 → momentum + meanrev                        │
│            - VWAP_Dist → meanrev                                │
│            - ATRp, BB_Width, Vol_Delta, Session_Heat → flow    │
│            - Funding_Bias, OI_Beta → positioning                │
│            - Event_Cooldown, Spread_Normalized → timing         │
│                                                                  │
│   Step 4b: Compute bucket scores                                │
│            score_i = Σ (weight_j * signal_j)                    │
│                                                                  │
│   Step 4c: Compute bucket directions                            │
│            dir_i = sign(score_i) if |score_i| >= 0.05 else 0   │
│                                                                  │
│   Step 4d: Compute bucket confidences                            │
│            conf_i = clip(|score_i|, 0, 1)                        │
│                                                                  │
│   Step 4e: Apply regime-specific weights                        │
│            Uses REGIME_BUCKET_WEIGHTS[regime]                    │
│            - trend_down: momentum(0.45), positioning(0.30), ... │
│            - high_vol: momentum(0.40), flow(0.30), ...         │
│            - chop: meanrev(0.50), timing(0.25), ...             │
│                                                                  │
│   Step 4f: Apply bucket masking (PAPER only)                    │
│            Uses REGIME_BUCKET_MASK[regime]                      │
│            - trend_up/down: only momentum + positioning         │
│            - high_vol: momentum + flow                          │
│                                                                  │
│   Step 4g: Aggregate to final_score                             │
│            final_score = Σ (weight_i * dir_i * conf_i) /        │
│                          Σ weights                              │
│                                                                  │
│   Step 4h: Compute final_dir, final_conf                        │
│            final_dir = sign(final_score)                        │
│            final_conf = clip(|final_score|, 0, 1)                │
│                                                                  │
│   Step 4i: Apply neutral zone                                   │
│            If |final_score| < 0.25: dir=0, conf=0.0             │
│                                                                  │
│   Step 4j: Round confidence to 2 decimals                      │
│                                                                  │
│ Output: {"final": {"dir": int, "conf": float, "score": float},  │
│          "buckets": {...}, "gates": {...}}                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. PHASE 54 ADJUSTMENTS (PAPER only)                            │
├─────────────────────────────────────────────────────────────────┤
│ Process: Apply regime-aware bucket weight multipliers           │
│          - trend_down/up: momentum +10%, flow +5%, positioning+5%│
│          - chop: meanrev +10%, flow -10%                        │
│          Recompute final_score with adjusted weights             │
│ Output: effective_final_dir, effective_final_conf               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. RISK ADAPTER EVALUATION                                      │
├─────────────────────────────────────────────────────────────────┤
│ Process: risk_eval() → {"band": "A"|"B"|"C", "mult": float}    │
│          - Band A: base thresholds                              │
│          - Band B: +0.03 to entry threshold                     │
│          - Band C: +0.05 to entry threshold                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. ENTRY GATING (autonomous_trader.py lines 970-1021)          │
├─────────────────────────────────────────────────────────────────┤
│ Step 7a: Regime Gate                                            │
│          if not regime_allows_entry(regime):                    │
│              BLOCK (only trend_down/high_vol allowed)           │
│                                                                  │
│ Step 7b: Confidence Threshold                                   │
│          entry_min_conf = compute_entry_min_conf(regime, band)  │
│          if effective_final_conf < entry_min_conf:             │
│              BLOCK                                              │
│                                                                  │
│ Step 7c: Direction Check                                        │
│          if effective_final_dir == 0:                            │
│              BLOCK (neutralized)                                 │
│                                                                  │
│ Step 7d: Policy Check                                           │
│          if not policy.get("allow_opens", True):                │
│              BLOCK                                              │
│                                                                  │
│ Step 7e: Call _try_open()                                       │
│          - Checks guardrails (cooldown, bad exits cluster)      │
│          - Calls open_if_allowed()                              │
│                                                                  │
│ Step 7f: open_if_allowed()                                      │
│          - Checks duplicate direction                            │
│          - Fetches entry_price from latest bar                  │
│          - Sets position via set_position()                     │
│          - Writes open event to trades.jsonl                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. EXIT EVALUATION (autonomous_trader.py lines 1023-1280)       │
├─────────────────────────────────────────────────────────────────┤
│ If position exists:                                              │
│                                                                  │
│   Step 8a: Evaluate Exit Conditions                            │
│            - TP: same_dir AND conf >= take_profit_conf (0.75)   │
│            - SL: opposite_dir AND conf >= stop_loss_conf (0.12) │
│            - Drop: conf < exit_min_conf (0.30)                  │
│            - Decay: bars_open >= decay_bars (6)                 │
│            - Reverse: opposite_dir AND conf >= reverse_conf(0.60)│
│                                                                  │
│   Step 8b: Min-Hold Guard                                       │
│            - Non-critical exits (TP, drop, reverse) blocked     │
│              if bars_open < MIN_HOLD_BARS_LIVE (4)              │
│            - Critical exits (SL) always allowed                 │
│                                                                  │
│   Step 8c: Compute P&L                                          │
│            entry_price = position["entry_px"]                   │
│            exit_price = latest_bar["close"]                     │
│            pct = (exit_price - entry_price) / entry_price *     │
│                  dir * 100.0                                    │
│                                                                  │
│   Step 8d: Call close_now()                                     │
│            - Computes is_scratch flag                           │
│            - Writes close event to trades.jsonl                 │
│            - Clears position                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔀 DIVERGENCE POINTS (Live vs Backtest)

### ✅ CONSISTENT (No Divergence)

1. **Regime Classification:** Same `classify_regime()` call, same window size
2. **Signal Processing:** Same `get_signal_vector_live()` call
3. **Confidence Aggregation:** Same `decide()` call with `regime_override`
4. **Entry Gating:** Same `regime_allows_entry()` and `compute_entry_min_conf()`
5. **Exit Logic:** Same conditions, same P&L calculation
6. **Neutral Zone:** Same threshold (0.25) for all modes

### ⚠️ DIFFERENCES (Data Source Only)

1. **OHLCV Source:**
   - Live: `get_live_ohlcv()` → API/exchange
   - Backtest: Mock `get_live_ohlcv()` → CSV window

2. **Trade Logging:**
   - Live: `reports/trades.jsonl`
   - Backtest: `reports/backtest/<run_id>/trades.jsonl` (via `CHLOE_TRADES_PATH`)

3. **Time Handling:**
   - Live: `datetime.now(timezone.utc)`
   - Backtest: `bar_ts` from CSV, `now=bar_dt` (simulated time)

---

## 🚫 ENTRY BLOCKERS (Why Trades Don't Open)

### Blocker #1: Regime Gate (CRITICAL)
- **Location:** `autonomous_trader.py` line 971
- **Condition:** `if not regime_allows_entry(price_based_regime)`
- **Impact:** Blocks ALL entries in `chop` and `trend_up`
- **Current State:** Most bars classified as `chop` → 100% blocked

### Blocker #2: Confidence Threshold
- **Location:** `autonomous_trader.py` line 992
- **Condition:** `if effective_final_conf < entry_min_conf`
- **Impact:** Blocks entries below threshold
- **Current State:** Thresholds: trend_down=0.48, high_vol=0.38

### Blocker #3: Neutral Zone
- **Location:** `autonomous_trader.py` line 699
- **Condition:** `if score_abs < NEUTRAL_THRESHOLD` (0.25)
- **Impact:** Sets `effective_final_dir = 0`, blocking entry
- **Current State:** ~50% of bars neutralized

### Blocker #4: Guardrails
- **Location:** `autonomous_trader.py` line 810-900
- **Conditions:**
  - Cooldown: 5 seconds between opens
  - Bad exits cluster: 3+ SL/drop in 10 seconds → block
  - Max 1 open per bar
- **Impact:** Prevents rapid-fire trading
- **Current State:** Usually not the blocker (no trades to trigger it)

---

## 📊 CURRENT STATE ANALYSIS

### Backtest Results (Recent)
- **All backtests:** 0 closes, PF = 0.0
- **Regime distribution:** 100% `chop` (from diagnostic)
- **Confidence distribution:** avg=0.28, max=0.85, ~50% neutralized

### Root Cause
1. **Regime classifier too conservative** → Everything is `chop`
2. **Regime gate blocks `chop`** → No entries possible
3. **Even if regime was allowed, thresholds might be too high**

---

## 🎯 FIX PRIORITY

1. **P0:** Fix regime classifier to detect `trend_down` and `high_vol` ✅ (Already fixed)
2. **P1:** Verify fixes work (run backtest on known trend period)
3. **P2:** If still 100% chop, lower thresholds further or use shorter windows
4. **P3:** Calibrate thresholds based on signal_return_analyzer output

---

**End of System Map**


