# Auto-Rotation Engine

## Overview

The Auto-Rotation Engine generates advisory recommendations for capital rotation between symbols based on:

- **Tier assignments** (tier1/2/3 from Reflection)
- **PF metrics** (short/long horizon from ARE)
- **Drift status** (improving/stable/degrading)
- **Microstructure regime** (clean_trend/noisy/indecision)
- **Execution quality** (friendly/neutral/hostile)

## Purpose

Helps identify which symbols to:

- **Overweight**: Strong performers with good execution
- **Underweight**: Weak performers with hostile execution
- **Hold**: Maintain current allocation

## Usage

Run the rotation engine:

```bash
python3 -m tools.run_auto_rotation
```

## Output

The tool writes `reports/research/auto_rotation_recs.json`:

```json
{
  "ETHUSDT": {
    "tier": "tier1",
    "drift": "improving",
    "exec_label": "friendly",
    "short_pf": 7.35,
    "long_pf": 14.12,
    "rotation": "overweight",
    "notes": ["Strong symbol: consider increasing allocation."]
  },
  "ADAUSDT": {
    "tier": "tier3",
    "drift": "degrading",
    "exec_label": "hostile",
    "short_pf": 1.26,
    "long_pf": 0.38,
    "rotation": "underweight",
    "notes": ["Weak & hostile: consider reducing allocation."]
  }
}
```

## Recommendations

### Overweight

Symbols that are:
- **Tier1** (strong performer)
- **Friendly execution** (good execution quality)
- **Improving or stable drift** (signal quality maintained/improving)

### Underweight

Symbols that are:
- **Tier3** (weak performer)
- **Hostile execution** (poor execution quality)

### Hold

All other symbols maintain current allocation.

## Safety

- **Advisory-only**: No automatic capital reallocation
- **Read-only**: Only reads research data
- **No auto-apply**: All recommendations require manual review

## Integration

The rotation engine can be added to the nightly research cycle:

```python
("AutoRotation", "tools.run_auto_rotation", "main"),
```

This makes rotation recommendations part of the regular intelligence gathering pipeline.

## Future Use

Once rotation patterns are validated, future phases may:

- Automatically adjust position sizing based on rotation recommendations
- Implement dynamic capital allocation between symbols
- Create rotation-aware portfolio management

All such changes will remain advisory-only until explicitly approved.

