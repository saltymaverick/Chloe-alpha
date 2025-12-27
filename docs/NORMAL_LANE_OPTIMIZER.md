# Normal Lane Optimizer

## Overview

The Normal Lane Optimizer identifies symbols where the **normal lane significantly outperforms the exploration lane**, indicating potential execution optimization opportunities.

## Purpose

When `norm_pf >> exp_pf` (especially for symbols like ETH), it suggests:

- **Exit rules** may be better tuned for normal lane
- **Position sizing** may be more appropriate for normal lane
- **Confidence gating** may be filtering out weak exploration trades effectively

This tool helps identify these opportunities for further investigation.

## Usage

Run the optimizer:

```bash
python3 -m tools.run_normal_lane_optimizer
```

## Output

The tool writes `reports/research/normal_lane_opportunities.json`:

```json
{
  "ETHUSDT": {
    "exp_pf": 7.35,
    "norm_pf": 14.12,
    "ratio": 1.92,
    "note": "normal lane significantly outperforms exploration"
  }
}
```

## Interpretation

If a symbol appears in the output:

1. **Investigate exit rules**: Normal lane may have better exit timing
2. **Review position sizing**: Normal lane sizing may be more appropriate
3. **Examine confidence gating**: Normal lane may be filtering weak trades better

## Criteria

A symbol is flagged if:

- `norm_pf > exp_pf * 1.5` (normal lane is 50%+ better)
- `norm_pf > 1.5` (normal lane is profitable)

## Safety

- **Advisory-only**: No config changes or trading logic modifications
- **Read-only**: Only reads ARE snapshot data
- **No auto-apply**: All recommendations require manual review

## Integration

The optimizer can be added to the nightly research cycle:

```python
("NormalLaneOptimizer", "tools.run_normal_lane_optimizer", "main"),
```

This makes it part of the regular intelligence gathering pipeline.

