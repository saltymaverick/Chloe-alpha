# Strategy Intelligence Dashboard

## Overview

The Strategy Intelligence Dashboard provides a unified, human-readable view of Chloe's research outputs and GPT reasoning. It consolidates data from multiple reports into a single CLI view, making it easy to assess Chloe's current intelligence state.

## Purpose

The dashboard helps you quickly understand:

- **Which symbols are strong/weak** (tiers, PF, quality scores)
- **Where to focus tuning/mutations** (tuner proposals, drift status)
- **Where execution is good/bad** (execution quality by regime)
- **Where GPT sees instability** (meta-reasoner issues, Dream patterns)

## Usage

Run the dashboard:

```bash
python3 -m tools.intel_dashboard
```

The dashboard prints a multi-section view to stdout with:

1. **Header**: Current time, mode (PAPER/SHADOW/LIVE), symbol count
2. **Symbol Summary Table**: Tier, exploration trades/PF, normal PF, drift status, quality score, execution quality
3. **Reflection Snapshot**: GPT's global notes and warnings
4. **Tuner Proposals**: Active tuning recommendations (non-zero deltas)
5. **Dream Patterns**: Scenario analysis summary per symbol
6. **Meta-Reasoner Issues**: Tier instability, contradictory tuning warnings
7. **Summary Footer**: Tier counts, top performers, de-risk candidates

## Data Sources

The dashboard reads from:

- `reports/research/are_snapshot.json` - Multi-horizon PF analysis
- `reports/research/drift_report.json` - Signal degradation tracking
- `reports/research/execution_quality.json` - Execution performance by regime
- `reports/gpt/quality_scores.json` - Per-symbol quality metrics
- `reports/gpt/reflection_output.json` - GPT tier assignments and insights
- `reports/gpt/tuner_output.json` - GPT tuning proposals
- `reports/gpt/dream_output.json` - GPT scenario analysis
- `reports/research/meta_reasoner_report.json` - Meta-reasoner warnings
- `config/symbols.yaml` - Enabled symbols list
- `config/engine_config.json` - Mode configuration

## Example Output

```
======================================================================
CHLOE ALPHA - STRATEGY INTELLIGENCE DASHBOARD
======================================================================
Time: 2025-01-15T10:30:00Z
Mode: PAPER
Symbols: 11

SYMBOL SUMMARY
----------------------------------------------------------------------
Symbol     Tier  ExpTr  ExpPF    NormPF   Drift        Qual  ExecQL
----------------------------------------------------------------------
ADAUSDT    T3    7      0.38     0.46     degrading    44    hostile
ATOMUSDT   T2    3      1.20     0.95     stable       48    neutral
BTCUSDT    T1    5      3.36     inf      stable       50    neutral
ETHUSDT    T1    10     14.12    0.92     improving    52    friendly
...

REFLECTION SNAPSHOT
----------------------------------------------------------------------
Notes:
  • ETHUSDT and BTCUSDT show strong exploration PF with improving drift
  • ADAUSDT and DOGEUSDT underperform in noisy microstructure regimes
Warnings:
  ⚠️  Tier instability detected for AVAXUSDT

TUNER PROPOSALS
----------------------------------------------------------------------
ETHUSDT: conf_min_delta=-0.02, exploration_cap_delta=+1  [loosen entry; expand exploration]
ADAUSDT: conf_min_delta=+0.02, exploration_cap_delta=-1  [tighten entry; reduce exploration]

DREAM PATTERNS
----------------------------------------------------------------------
ETHUSDT: good=5, bad=0, improve=1
DOGEUSDT: good=0, bad=3, improve=1

Key Patterns:
  • Most bad trades occur in tier3 symbols in noisy/chop regimes
  • ETH/BTC perform best in clean_trend microstructure

META-REASONER ISSUES
----------------------------------------------------------------------
[tier_instability] AVAXUSDT
  • Flipped between tier1 and tier2 in 3 of last 5 cycles

Recommendations:
  • Reduce tuning frequency for AVAXUSDT and XRPUSDT until tiers stabilize

SUMMARY
----------------------------------------------------------------------
Tier1 symbols (6): BTCUSDT, ETHUSDT, DOTUSDT, BNBUSDT, AVAXUSDT, XRPUSDT
Tier2 symbols (3): ATOMUSDT, LINKUSDT, SOLUSDT
Tier3 symbols (2): ADAUSDT, DOGEUSDT

Top Exploration PF:
  • ETHUSDT (14.12)
  • DOTUSDT (4.82)
  • BTCUSDT (3.36)

Top Quality Scores:
  • ETHUSDT (52)
  • BTCUSDT (50)
  • DOTUSDT (48)

De-risk candidates:
  • ADAUSDT, DOGEUSDT (weak PF, poor Dream patterns)
```

## Safety

- **Read-only**: Only reads report files, never modifies configs or trading logic
- **Advisory-only**: All data is for information purposes
- **Graceful degradation**: Handles missing files gracefully, shows "?" or "No data" where appropriate
- **No exchange calls**: Uses existing data files only

## Integration

The dashboard is designed to be run:

- **After nightly research cycle**: `python3 -m tools.nightly_research_cycle && python3 -m tools.intel_dashboard`
- **On-demand**: Run anytime to see current intelligence state
- **In monitoring scripts**: Can be piped to logs or files for historical tracking

## Future Enhancements

Potential future additions:

- Historical trend visualization (PF over time)
- Comparison mode (compare two time periods)
- Export to JSON/CSV for external analysis
- Interactive mode with filtering/search

All enhancements will remain read-only and advisory-only.
