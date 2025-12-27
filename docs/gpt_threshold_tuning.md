# GPT-Guided Threshold Tuning

## Overview

Chloe now has a data-driven, GPT-guided tuning system for entry thresholds. This replaces manual threshold guessing with an automated analysis → GPT recommendation → application workflow.

## Tools

### 1. `tools/signal_return_analyzer.py`

**Purpose**: Analyzes historical OHLCV data by running Chloe's real signal pipeline and summarizing performance by regime × confidence bin.

**What it does**:
- Loads OHLCV CSV
- For each bar, computes:
  - Price-based regime (using `classify_regime`)
  - Signal vector and confidence (using `get_signal_vector_live` + `decide`)
  - Effective final direction/confidence (with Phase 54 adjustments and neutral zone)
- Simulates 1-bar forward returns (what would happen if we traded at this confidence)
- Buckets results by regime × confidence bin (e.g., trend_down × [0.60-0.65))
- Computes statistics: count, wins, losses, PF, avg_return, median_return

**Output**: `reports/analysis/conf_ret_summary.json`

**Usage**:
```bash
python3 -m tools.signal_return_analyzer \
  --symbol ETHUSDT \
  --timeframe 1h \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --window 200 \
  --step-horizon 1 \
  --output reports/analysis/conf_ret_summary.json
```

### 2. `tools/gpt_threshold_tuner.py`

**Purpose**: Uses GPT to read the analysis summary and propose new per-regime entry thresholds.

**What it does**:
- Loads `conf_ret_summary.json`
- Aggregates performance by regime
- Calls OpenAI GPT with:
  - Current thresholds
  - Performance summary by regime
  - Top-performing confidence bins
- Gets JSON recommendations for new thresholds
- Optionally writes to `config/entry_thresholds.json`

**Usage**:
```bash
# Dry run (just prints recommendations)
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json

# Apply recommendations
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json \
  --apply
```

## Workflow

1. **Run analyzer** over full historical CSV:
   ```bash
   python3 -m tools.signal_return_analyzer \
     --csv data/ohlcv/ETHUSDT_1h_merged.csv \
     --output reports/analysis/conf_ret_summary.json
   ```

2. **Review GPT recommendations** (dry run):
   ```bash
   python3 -m tools.gpt_threshold_tuner \
     --summary reports/analysis/conf_ret_summary.json
   ```

3. **Apply if recommendations look good**:
   ```bash
   python3 -m tools.gpt_threshold_tuner \
     --summary reports/analysis/conf_ret_summary.json \
     --apply
   ```

4. **Restart Chloe** to use new thresholds (they're loaded via `compute_entry_min_conf()`)

## Integration

- ✅ Uses existing `config/entry_thresholds.json`
- ✅ Wired into `compute_entry_min_conf(regime, risk_band)` 
- ✅ No changes to exit logic
- ✅ No LAB_MODE/ANALYSIS_MODE hacks
- ✅ Same code path for live and backtest
- ✅ Respects `regime_allows_entry()` (currently only trend_down and high_vol)

## Output Format

### `conf_ret_summary.json`:
```json
{
  "symbol": "ETHUSDT",
  "timeframe": "1h",
  "window": 200,
  "step_horizon": 1,
  "generated_at": "2025-11-23T18:00:00Z",
  "bins": [
    {
      "regime": "trend_down",
      "conf_min": 0.60,
      "conf_max": 0.65,
      "count": 1234,
      "wins": 600,
      "losses": 400,
      "pos_sum": 1.23,
      "neg_sum": 0.85,
      "pf": 1.45,
      "avg_return": 0.00031,
      "median_return": 0.00020
    },
    ...
  ]
}
```

### GPT Recommendations:
```json
{
  "trend_down": {"enabled": true,  "entry_min_conf": 0.52},
  "high_vol":   {"enabled": true,  "entry_min_conf": 0.58},
  "trend_up":   {"enabled": false, "entry_min_conf": 0.65},
  "chop":       {"enabled": false, "entry_min_conf": 0.75}
}
```

## Notes

- The analyzer uses the **exact same logic** as `run_step_live()`:
  - Same regime classification
  - Same signal processing
  - Same Phase 54 adjustments
  - Same neutral zone logic
- This ensures the analysis reflects what would actually happen in live trading
- GPT recommendations are advisory only - human review recommended before applying
- The `enabled` flag in GPT recommendations is for future use (not yet wired into `regime_allows_entry()`)


