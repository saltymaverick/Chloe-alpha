# GPT-Quant Analyzer V1

**Date:** 2024-11-23  
**Status:** ✅ Implemented

---

## Overview

GPT-Quant Analyzer V1 is a complete pipeline that:
1. Sweeps the entire ETH 1h CSV
2. Computes quantitative features per bar/window
3. Runs Chloe's regime & confidence logic
4. Has GPT analyze the data like a professional quant
5. Proposes regime enable/disable and entry thresholds
6. Writes thresholds back to `config/entry_thresholds.json`

---

## Architecture

```
CSV → quant_features.py → quant_feature_dump.py → quant_windows.jsonl → gpt_quant_analyst.py → entry_thresholds.json
```

### Components

1. **`engine_alpha/signals/quant_features.py`**
   - Pure feature extractor (no trading side-effects)
   - Computes: returns, volatility, EMA slopes, RSI, Bollinger/Keltner bands, squeeze

2. **`tools/quant_feature_dump.py`**
   - Loads CSV, slides window
   - For each bar: computes features, regime, confidence, forward return
   - Writes JSONL dataset: `reports/analysis/quant_windows.jsonl`

3. **`tools/gpt_quant_analyst.py`**
   - Reads JSONL dataset
   - Builds regime × confidence bin summary
   - Calls GPT with quantitative prompt
   - Extracts threshold recommendations
   - Optionally writes to `config/entry_thresholds.json`

---

## Usage

### Step A: Generate Quant Windows

```bash
cd /root/Chloe-alpha
export PYTHONPATH=/root/Chloe-alpha

python3 -m tools.quant_feature_dump \
  --symbol ETHUSDT \
  --timeframe 1h \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --window 200 \
  --horizon 1 \
  --output reports/analysis/quant_windows.jsonl
```

This will:
- Load the CSV
- Compute quant features for each bar
- Run Chloe's regime & confidence logic
- Compute 1h forward returns
- Write JSONL dataset

**Expected output:** `reports/analysis/quant_windows.jsonl` with ~tens of thousands of records

### Step B: GPT Quant Analysis

```bash
export OPENAI_API_KEY=your_key_here

python3 -m tools.gpt_quant_analyst \
  --windows reports/analysis/quant_windows.jsonl \
  --model gpt-4o \
  --apply
```

This will:
- Load the JSONL dataset
- Build regime × confidence bin summary
- Call GPT with quantitative prompt
- Print proposed thresholds table
- Write new thresholds to `config/entry_thresholds.json` (if `--apply`)

**Expected output:**
```
=== PROPOSED THRESHOLDS ===

Regime       Enable   Old    New    Notes
--------------------------------------------------------------------------------
trend_down   True     0.52   0.50   Profitable across most bands...
high_vol     True     0.58   0.55   Best in moderate confidence...
trend_up     True     0.60   0.48   Profitable in post-capitulation...
chop         False    0.65   0.65   PF weak except for tiny pockets...

✅ Updated thresholds written to config/entry_thresholds.json
```

---

## Integration with Chloe

The thresholds written to `config/entry_thresholds.json` are automatically used by:
- `engine_alpha/loop/autonomous_trader.py` → `compute_entry_min_conf()`
- Unified code path (no special modes needed)
- Live, PAPER, and backtest all use the same thresholds

---

## Features Computed

- **Returns:** 1h, 4h, 24h (clipped to guard extremes)
- **Volatility:** 14-bar and 50-bar stdev, ATR
- **Trend:** EMA fast/slow slopes
- **Oscillators:** RSI(14)
- **Bands:** Bollinger width, Keltner width
- **Squeeze:** BB inside KC (contraction indicator)

---

## GPT Prompt

The GPT prompt instructs it to:
- Analyze performance by regime × confidence bin
- Require at least ~50 samples before trusting
- Favor lower thresholds when PF>1.5 and sample size is good
- Favor higher thresholds or disabling when PF<1.0
- Note feature patterns that correlate with good PF

---

## Next Steps (Future Iterations)

- Let GPT propose regime reclassification rules
- Let GPT propose feature-gated entries (e.g., only enter trend_up if squeeze_on=1)
- Start shaping a true meta-strategy layer

---

## Files Created

1. `engine_alpha/signals/quant_features.py` - Feature extractor
2. `tools/quant_feature_dump.py` - Window sweeper
3. `tools/gpt_quant_analyst.py` - GPT analyzer
4. `docs/gpt_quant_analyzer_v1.md` - This documentation

---

## Dependencies

- `pandas` - DataFrame operations
- `numpy` - Numerical operations
- `openai` - GPT API client

Install with:
```bash
pip install pandas numpy openai
```

---

## Notes

- The feature dump can take 10-30 minutes for a full ETH history CSV
- GPT analysis typically takes 10-60 seconds depending on model
- All thresholds are clamped to [0.35, 0.85] for safety
- The system respects Chloe's unified code path (no hacks)
