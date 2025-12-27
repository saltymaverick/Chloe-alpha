# Execution Quality Analyzer

## Overview

The Execution Quality Analyzer measures how well Chloe's execution performs in different microstructure regimes by analyzing realized trades against microstructure snapshots. This provides insight into which symbols and regimes are execution-friendly vs execution-hostile.

## What It Measures

The analyzer computes the following metrics per symbol and micro_regime:

- **Average realized pct**: Mean percentage return in each regime
- **Win rate**: Percentage of profitable trades
- **Big win/big loss counts**: Trades with pct ≥ +1% or ≤ -1%
- **Sample size**: Number of trades in each regime
- **Label**: Qualitative assessment:
  - **friendly**: avg_pct > 0 and win_rate > 0.55
  - **hostile**: avg_pct < 0 or big_loss > big_win
  - **neutral**: everything else

## How It Works

1. **Loads trades**: Reads `reports/trades.jsonl` for closed trades
2. **Loads microstructure**: Reads `reports/research/microstructure_snapshot_15m.json` for regime classifications
3. **Matches trades to regimes**: Associates each trade with its microstructure regime
4. **Computes metrics**: Calculates performance statistics per (symbol, micro_regime) pair
5. **Generates report**: Writes `reports/research/execution_quality.json`

## Usage

### Run the analyzer:

```bash
python3 -m tools.run_execution_quality_scan
```

### Output format:

The report is written to `reports/research/execution_quality.json`:

```json
{
  "generated_at": "2025-01-15T10:30:00Z",
  "data": {
    "ETHUSDT": {
      "clean_trend": {
        "trades": 12,
        "avg_pct": 0.0075,
        "win_rate": 0.67,
        "big_win": 3,
        "big_loss": 1,
        "label": "friendly"
      },
      "noisy": {
        "trades": 5,
        "avg_pct": -0.0010,
        "win_rate": 0.40,
        "big_win": 0,
        "big_loss": 2,
        "label": "hostile"
      }
    }
  }
}
```

## Integration with Reflection/Tuner/Dream v4

The execution quality data is automatically loaded into Reflection/Tuner/Dream v4 payloads when available. GPT can use this to:

- **Reflection v4**: Note patterns like "ETHUSDT is friendly in clean_trend, neutral in noisy"
- **Tuner v4**: Suggest tuning out hostile regimes for weak symbols
- **Dream v4**: Identify recurring failure modes linked to microstructure regimes

## Nightly Research Cycle

The Execution Quality Analyzer runs automatically as part of the nightly research cycle:

```bash
python3 -m tools.nightly_research_cycle
```

It appears as:
```
[OK] ExecutionQuality
```

## Safety

- **Advisory-only**: No changes to trading logic or configs
- **Read-only**: Only reads trades and microstructure data
- **Non-crashing**: Gracefully handles missing data
- **No exchange calls**: Uses existing data files only

## Future Use

Once execution quality patterns are identified, future phases may:

- Automatically adjust entry/exit thresholds based on microstructure regime
- Skip trades in hostile regimes for specific symbols
- Optimize position sizing based on regime-specific execution quality

All such changes will remain advisory-only until explicitly approved.

