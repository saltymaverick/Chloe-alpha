# Paper Tuning Overrides

## Overview

The **Paper Tuning Override Layer** provides a safe, controlled way to automatically apply small tuning adjustments for Tier1 symbols in **PAPER mode only**. This system reads tuner v4 recommendations, rotation signals, and tier assignments, then applies tiny deltas to entry confidence thresholds and exploration capacity limits.

**Key Safety Guarantees:**
- ✅ PAPER mode only — LIVE mode completely ignores overrides
- ✅ Tier1 symbols only — only applies to symbols with strongest evidence
- ✅ Small deltas only — conf_min_delta in [-0.02, 0.02], exploration_cap_delta in [-1, 1]
- ✅ No core config changes — overrides stored separately in `config/paper_tuning_overrides.json`
- ✅ Accumulation limits — total overrides clamped to safe bounds

## How It Works

### 1. Apply Tuner Recommendations

Run the paper tuning apply tool:

```bash
python3 -m tools.run_paper_tuning_apply
```

This tool:
- Reads `reports/gpt/tuner_output.json` (tuner v4 proposals)
- Reads `reports/research/auto_rotation_recs.json` (rotation recommendations)
- Loads tier assignments from reflection output
- Filters proposals to only Tier1 symbols with:
  - Rotation: `overweight` or `hold` (not `underweight`)
  - Small deltas: `conf_min_delta` in [-0.02, 0.02], `exploration_cap_delta` in [-1, 1]
- Accumulates deltas into `config/paper_tuning_overrides.json`

### 2. Override File Format

`config/paper_tuning_overrides.json`:

```json
{
  "generated_at": "2025-12-05T21:00:00+00:00",
  "mode": "PAPER_ONLY",
  "overrides": {
    "ETHUSDT": {
      "conf_min_delta": -0.01,
      "exploration_cap_delta": 1,
      "notes": [
        "Applied +0.010/+1 from tuner v4 (2025-12-05T21:00:00+00:00)",
        "Applied -0.020/+0 from tuner v4 (2025-12-05T21:01:00+00:00)"
      ]
    },
    "BTCUSDT": {
      "conf_min_delta": 0.02,
      "exploration_cap_delta": 0,
      "notes": [
        "Applied +0.020/+0 from tuner v4 (2025-12-05T21:00:00+00:00)"
      ]
    }
  }
}
```

### 3. Trading Loop Integration

The trading loop automatically reads overrides in PAPER mode:

**Entry Confidence Adjustment:**
- `open_if_allowed()` applies `conf_min_delta` to `entry_min_conf` threshold
- Only in PAPER mode
- Clamped to [0.0, 1.0]

**Exploration Capacity Adjustment:**
- Exploration lane checks apply `exploration_cap_delta` to `max_open_per_symbol`
- Only in PAPER mode
- Clamped to [1, 5]

## Usage

### Manual Apply

```bash
# Run tuner cycle first
python3 -m tools.run_tuner_cycle

# Apply tuner recommendations as paper overrides
python3 -m tools.run_paper_tuning_apply
```

### Integration with Nightly Cycle

Add to `tools/nightly_research_cycle.py` (optional):

```python
research_steps = [
    # ... existing steps ...
    ("PaperTuningApply", "tools.run_paper_tuning_apply", "main"),
]
```

This will automatically apply tuner recommendations after each nightly research cycle.

## Safety Limits

### Accumulation Limits

Even if multiple tuner cycles recommend changes, total accumulated overrides are clamped:

- `conf_min_delta`: Accumulated total clamped to [-0.05, +0.05]
- `exploration_cap_delta`: Accumulated total clamped to [-3, +3]

### Filtering Rules

Overrides are only applied for symbols that meet ALL criteria:

1. **Tier1 only** — Tier2/Tier3 symbols are ignored
2. **Rotation status** — Must be `overweight` or `hold` (not `underweight`)
3. **Delta bounds** — Individual deltas must be within safe ranges
4. **PAPER mode only** — LIVE mode completely ignores overrides

## Examples

### Example 1: ETHUSDT (Tier1, Overweight, Friendly Execution)

**Tuner Proposal:**
```json
{
  "proposals": {
    "ETHUSDT": {
      "conf_min_delta": -0.01,
      "exploration_cap_delta": 1,
      "notes": ["Strong performer: slight relaxation"]
    }
  }
}
```

**Rotation:**
```json
{
  "ETHUSDT": {
    "rotation": "overweight",
    "tier": "tier1"
  }
}
```

**Result:** Override applied ✅
- `conf_min_delta`: -0.01 (entry threshold lowered by 0.01)
- `exploration_cap_delta`: +1 (exploration capacity increased by 1)

### Example 2: ADAUSDT (Tier3, Underweight, Hostile Execution)

**Tuner Proposal:**
```json
{
  "proposals": {
    "ADAUSDT": {
      "conf_min_delta": -0.02,
      "exploration_cap_delta": -1
    }
  }
}
```

**Rotation:**
```json
{
  "ADAUSDT": {
    "rotation": "underweight",
    "tier": "tier3"
  }
}
```

**Result:** Override NOT applied ❌
- Tier3 symbol (filtered out)
- Underweight rotation (filtered out)

## Monitoring

### Check Current Overrides

```bash
cat config/paper_tuning_overrides.json | jq
```

### View Override Application Logs

Enable debug signals to see when overrides are applied:

```bash
export DEBUG_SIGNALS=1
python3 -m tools.run_autonomous_trader
```

You'll see logs like:
```
PAPER-TUNING: ETHUSDT entry_min_conf adjusted by -0.010 (0.700 -> 0.690)
PAPER-TUNING: ETHUSDT exploration cap adjusted by +1 (2 -> 3)
```

## Troubleshooting

### No Overrides Applied

**Possible reasons:**
- No tuner proposals for Tier1 symbols
- All Tier1 symbols have `underweight` rotation
- Deltas outside safe bounds [-0.02, 0.02] or [-1, 1]
- Tuner output file missing or malformed

**Check:**
```bash
# Verify tuner output exists
cat reports/gpt/tuner_output.json | jq '.proposals'

# Verify rotation recommendations
cat reports/research/auto_rotation_recs.json | jq

# Verify tiers
cat reports/gpt/reflection_output.json | jq '.tiers'
```

### Overrides Not Taking Effect

**Check:**
1. Mode is PAPER: `echo $MODE` should be `PAPER`
2. Override file exists: `ls -la config/paper_tuning_overrides.json`
3. Symbol is in override file: `cat config/paper_tuning_overrides.json | jq '.overrides.ETHUSDT'`
4. Trading loop is reading overrides (check logs with `DEBUG_SIGNALS=1`)

## Future Enhancements

Potential future improvements:

1. **Consistency checks** — Only apply if tuner recommends same delta for N consecutive nights
2. **Rollback mechanism** — Auto-revert if performance degrades after override
3. **Per-symbol history** — Track override application history and performance impact
4. **Gradual application** — Apply deltas gradually over multiple cycles instead of all at once

## Safety Reminders

⚠️ **This system is PAPER-ONLY. LIVE mode completely ignores overrides.**

⚠️ **Core configs are never modified. All changes are in the override file.**

⚠️ **Only small, safe deltas are applied. Large changes require manual review.**

⚠️ **Tier1 symbols only. Lower-tier symbols are excluded for safety.**

