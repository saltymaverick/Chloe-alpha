# Tuning Reason Log

## Overview

The **Tuning Reason Log** provides structured explanations of why GPT Tuner v4 makes its tuning proposals. This creates full explainability for Chloe's tuning decisions, capturing the context and reasoning behind each adjustment.

**Purpose:**
- Human review and understanding of tuning decisions
- Future self-evaluation and Tuner v5 development
- Audit trail of tuning rationale over time
- Debugging and troubleshooting tuning behavior

## Location

**File:** `reports/gpt/tuning_reason_log.jsonl`

**Format:** JSONL (JSON Lines) - one entry per tuning cycle

## Format

Each line in the log file is a JSON object with the following structure:

```json
{
  "ts": "2025-12-05T21:15:00+00:00",
  "symbols": {
    "ETHUSDT": {
      "tier": "tier1",
      "drift": "improving",
      "short_pf": 7.35,
      "long_pf": 17.49,
      "micro_regime": "clean_trend",
      "exec_label": "friendly",
      "rotation": "overweight",
      "proposal": {
        "conf_min_delta": 0.02,
        "exploration_cap_delta": 1,
        "notes": ["Strong performer: slight relaxation"]
      },
      "reasons": [
        "Tier: tier1",
        "Short-horizon PF: 7.35",
        "Long-horizon PF: 17.49",
        "Drift status: improving",
        "Microstructure regime: clean_trend",
        "Execution quality: friendly",
        "Rotation recommendation: overweight"
      ],
      "warnings": []
    },
    "ADAUSDT": {
      "tier": "tier3",
      "drift": "insufficient_data",
      "short_pf": 0.00,
      "long_pf": 0.37,
      "micro_regime": "clean_trend",
      "exec_label": "hostile",
      "rotation": "underweight",
      "proposal": {
        "conf_min_delta": 0.02,
        "exploration_cap_delta": -1,
        "notes": ["Weak performer: tighten criteria"]
      },
      "reasons": [
        "Tier: tier3",
        "Short-horizon PF: 0.00",
        "Long-horizon PF: 0.37",
        "Drift status: insufficient_data",
        "Microstructure regime: clean_trend",
        "Execution quality: hostile",
        "Rotation recommendation: underweight"
      ],
      "warnings": [
        "Meta issue: tier_instability"
      ]
    }
  },
  "global_notes": [
    "Tier1 symbols: BNBUSDT, BTCUSDT, DOTUSDT, ETHUSDT",
    "Tier3 symbols: ADAUSDT, DOGEUSDT, LINKUSDT"
  ],
  "meta_issues": [
    {
      "type": "tier_instability",
      "symbols": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"],
      "details": "..."
    }
  ]
}
```

### Field Descriptions

**Top-level fields:**
- `ts`: ISO timestamp of the tuning cycle
- `symbols`: Dict mapping symbol -> tuning reason data
- `global_notes`: High-level summary notes (tier distributions, etc.)
- `meta_issues`: Meta-reasoner warnings and issues

**Per-symbol fields:**
- `tier`: Symbol tier assignment (tier1/tier2/tier3)
- `drift`: Drift status (improving/stable/degrading/insufficient_data)
- `short_pf`: Short-horizon profit factor from ARE
- `long_pf`: Long-horizon profit factor from ARE
- `micro_regime`: Dominant microstructure regime (clean_trend/indecision/etc.)
- `exec_label`: Execution quality label (friendly/neutral/hostile)
- `rotation`: Auto-rotation recommendation (overweight/hold/underweight)
- `proposal`: The actual tuning proposal (conf_min_delta, exploration_cap_delta, notes)
- `reasons`: List of human-readable reasons explaining the proposal
- `warnings`: List of meta-reasoner warnings for this symbol

## How to View

### View Latest Entry

```bash
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool
```

### View Last 3 Entries

```bash
tail -n 3 reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool
```

### View All Entries

```bash
cat reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool
```

### View in Intel Dashboard

The intel dashboard automatically shows the latest tuning reasons:

```bash
python3 -m tools.intel_dashboard
```

Look for the "TUNING REASONS (LATEST)" section at the bottom.

### Filter by Symbol

```bash
cat reports/gpt/tuning_reason_log.jsonl | python3 -c "
import json, sys
for line in sys.stdin:
    entry = json.loads(line)
    if 'ETHUSDT' in entry.get('symbols', {}):
        print(json.dumps(entry, indent=2))
"
```

## How It Works

### Automatic Logging

The tuning reason log is automatically appended after each successful tuner cycle:

1. `tools/run_tuner_cycle.py` runs and generates `tuner_output.json`
2. After writing the tuner output, it calls `append_tuning_reason_entry()`
3. The logger reads all context data (ARE, drift, microstructure, etc.)
4. It builds a structured explanation entry
5. The entry is appended to `tuning_reason_log.jsonl`

### Data Sources

The logger reads from:

- `reports/gpt/tuner_output.json` - Tuner proposals
- `reports/research/are_snapshot.json` - Profit factors
- `reports/research/drift_report.json` - Drift status
- `reports/research/microstructure_snapshot_15m.json` - Microstructure regimes
- `reports/research/execution_quality.json` - Execution quality labels
- `reports/gpt/reflection_output.json` - Tier assignments
- `reports/research/auto_rotation_recs.json` - Rotation recommendations
- `reports/research/meta_reasoner_report.json` - Meta-reasoner warnings

### Error Handling

If logging fails (e.g., missing data files), the error is printed but does not crash the tuner cycle. The tuner continues normally even if reason logging fails.

## Usage Examples

### Example 1: Review Latest Tuning Decisions

```bash
# Get latest entry
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool | less

# Focus on ETHUSDT
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -c "
import json, sys
entry = json.loads(sys.stdin.read())
eth = entry['symbols'].get('ETHUSDT', {})
print('ETHUSDT Tuning Reasons:')
for r in eth.get('reasons', []):
    print(f'  - {r}')
print(f'\nProposal: {eth.get(\"proposal\", {})}')
"
```

### Example 2: Track Tuning History

```bash
# Count tuning cycles
wc -l reports/gpt/tuning_reason_log.jsonl

# See when tuning happened
cat reports/gpt/tuning_reason_log.jsonl | python3 -c "
import json, sys
for line in sys.stdin:
    entry = json.loads(line)
    print(entry['ts'])
"
```

### Example 3: Compare Tuning Across Symbols

```bash
# See all symbols that got proposals in latest cycle
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -c "
import json, sys
entry = json.loads(sys.stdin.read())
for sym, info in entry['symbols'].items():
    props = info['proposal']
    print(f'{sym}: conf_delta={props.get(\"conf_min_delta\")} cap_delta={props.get(\"exploration_cap_delta\")}')
"
```

## Future Enhancements

Potential future improvements:

1. **Self-Evaluation Module** - Compare tuning_reason entries vs subsequent PF changes to let Chloe grade her own tuning moves
2. **Tuning Effectiveness Metrics** - Track whether tuning proposals actually improved performance
3. **Pattern Detection** - Identify recurring tuning patterns and their outcomes
4. **Tuner v5** - Use historical tuning reasons to train a better tuner

## Integration

The tuning reason log integrates with:

- **Intel Dashboard** - Shows latest tuning reasons
- **Paper Tuning Overrides** - Can reference tuning reasons when applying overrides
- **Meta-Reasoner** - Uses tuning reasons to detect contradictions
- **Future Self-Evaluation** - Will compare reasons vs outcomes

## Troubleshooting

### No Log Entries

**Possible reasons:**
- Tuner cycle hasn't run yet
- Tuner cycle failed before writing output
- Logger encountered an error (check logs)

**Check:**
```bash
# Verify tuner output exists
ls -la reports/gpt/tuner_output.json

# Run tuner cycle manually
python3 -m tools.run_tuner_cycle

# Check for errors
tail -n 20 logs/*.log | grep -i tuning
```

### Missing Data in Reasons

**Possible reasons:**
- Research files missing (ARE, drift, microstructure, etc.)
- Data format changed
- Logger couldn't parse data

**Check:**
```bash
# Verify all data sources exist
ls -la reports/research/*.json
ls -la reports/gpt/reflection_output.json

# Check latest entry for missing fields
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool | grep -A 5 "ETHUSDT"
```

## Safety

⚠️ **The tuning reason log is read-only and advisory-only.**

⚠️ **It does not affect trading behavior or configs.**

⚠️ **It only records what happened, not what should happen.**

