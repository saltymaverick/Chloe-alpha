# Microstructure Engine v1

## Overview

The **Microstructure Engine v1** approximates intrabar structure using OHLCV bar geometry. It classifies bars into micro regimes and provides features for future use in GPT Reflection, Tuner, Dream, and exit/timing refinements.

## Purpose

The Microstructure Engine enables:
- **Bar-level intelligence**: Understand the internal structure of each bar
- **Regime classification**: Identify clean trends vs noisy markets
- **Feature extraction**: Compute wick ratios, body ratios, volatility, momentum
- **Research context**: Feed richer data into GPT Reflection/Tuner/Dream

## Micro Regimes

The engine classifies each bar into one of four micro regimes:

### clean_trend
- **Characteristics**: High body ratio (>0.6), small wicks (<0.3 combined)
- **Interpretation**: Strong directional movement with minimal indecision
- **Use case**: Safer entries, reliable trend continuation

### noisy
- **Characteristics**: Large wicks relative to body (>0.5 combined)
- **Interpretation**: High indecision, choppy price action
- **Use case**: Avoid entries, reduce position sizing

### reversal_hint
- **Characteristics**: Extreme wick imbalance
  - Large upper wick in uptrend (>0.5)
  - Large lower wick in downtrend (>0.5)
- **Interpretation**: Potential reversal signal
- **Use case**: Caution on entries, consider exits

### indecision
- **Characteristics**: Very small body ratio (<0.2)
- **Interpretation**: Market uncertainty, lack of direction
- **Use case**: Avoid entries, wait for clearer signals

## Features Computed

For each bar, the engine computes:

- **body**: Absolute difference between open and close
- **range**: High - low
- **upper_wick**: High - max(open, close)
- **lower_wick**: min(open, close) - low
- **body_ratio**: body / range (0-1, higher = stronger direction)
- **upper_wick_ratio**: upper_wick / range (0-1)
- **lower_wick_ratio**: lower_wick / range (0-1)
- **volatility**: range / previous_close (normalized range)
- **momentum**: (close - previous_close) / previous_close
- **gap**: (open - previous_close) / previous_close
- **wick_imbalance**: upper_wick_ratio - lower_wick_ratio
- **trend_bar**: 1 (up), -1 (down), or 0 (flat)
- **micro_regime**: Classification (clean_trend/noisy/reversal_hint/indecision)

## File Locations

### Output
- **Snapshot**: `reports/research/microstructure_snapshot_15m.json`
  - Structure: `{symbol: {timestamp: features}}`
  - Updated by: `tools/run_microstructure_scan.py`

### Data Sources
- **Live prices**: Uses `engine_alpha.data.live_prices.get_live_ohlcv()`
- **Historical fallback**: Uses `engine_alpha.data.historical_prices.load_ohlcv_csv()`

## Usage

### Manual Execution
```bash
python3 -m tools.run_microstructure_scan
```

### Automatic Execution
Microstructure scan runs automatically in nightly research cycle (if integrated):
```bash
python3 -m tools.nightly_research_cycle
```

### Inspect Output
```bash
cat reports/research/microstructure_snapshot_15m.json | less
```

## Integration with GPT Modules

The microstructure snapshot is optionally included in:
- **Reflection input**: `reflection_input["microstructure"]`
- **Tuner input**: `tuner_input["microstructure"]`
- **Dream input**: `dream_input["microstructure"]`

GPT can use this data to:
- Identify symbols that live in noisy microstructure
- Treat clean_trend bars as safer entry points
- Adjust tier assignments based on micro regime patterns
- Provide richer context for scenario analysis

## Example Usage in GPT Prompts

### Reflection v4 (Future)
```
"ETHUSDT shows 85% clean_trend bars in recent microstructure analysis.
This supports tier1 assignment and suggests reliable signal quality."
```

### Tuner v4 (Future)
```
"DOGEUSDT has 70% noisy bars. Avoid loosening thresholds for this symbol.
Keep exploration cap low and entry confidence high."
```

### Dream v4 (Future)
```
"Scenario occurred during noisy micro regime. This explains the poor exit timing.
Consider avoiding entries when microstructure is noisy."
```

## Current Limitations

- **OHLCV-based only**: No direct orderbook access
- **Approximation**: Intrabar structure is inferred from bar geometry
- **Timeframe**: Currently supports 15m (extensible to other timeframes)
- **No live integration**: Not wired into trading loop yet

## Future Enhancements

### v2 Features (Potential)
- Multi-timeframe analysis (15m + 1h + 4h)
- Volume-weighted microstructure
- Cross-symbol microstructure correlation
- Regime persistence tracking

### v3 Features (Potential)
- Orderbook depth integration (if available)
- Spread analysis
- Fill quality estimation
- Slippage prediction

## Safety Guarantees

✅ **Advisory-only**: No trading behavior changes  
✅ **Research-oriented**: Outputs only to reports/research/  
✅ **No config writes**: Does not modify any configs  
✅ **No exchange calls**: Uses existing OHLCV data  
✅ **Optional integration**: GPT modules work with or without microstructure data

## Related Documentation

- [Aggregated Research Engine](./docs/ARE.md)
- [Reflection v3](./docs/REFLECTION_V3.md)
- [Tuner v3](./docs/TUNER_V3.md)
- [Dream v3](./docs/DREAM_V3.md)

