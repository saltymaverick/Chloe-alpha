# Chloe Tuning Roadmap

## Overview

This document defines the tuning roadmap for Chloe's multi-asset trading engine. It establishes clear tiers, thresholds, and rules for promotion/demotion and tuning decisions.

## Architecture Recap

Chloe operates with:

- **Paper Trading**: All trades are simulated (no real capital at risk)
- **Exploration Lane**: `trade_kind="exploration"` - small, exploratory trades to gather data
- **Normal Lane**: `trade_kind="normal"` - standard trading after sufficient exploration
- **GPT Scaffolding**: Reflection → Tuner → Dream pipeline for analysis and tuning proposals
- **Shadow Mode**: `BYBIT_SHADOW_MODE=true` blocks all real orders (safety layer)

## Symbol Tiers

### Tier 1 (Core Assets)

**Definition**: Strong performers ready for positive tuning and promotion.

**Criteria**:
- Exploration PF >= 1.5
- Exploration trades ≥ 4
- Normal PF >= 1.0 (or "inf" with at least 1 trade)
- Stable behavior (no wild swings in PF)
- Dream/Debrief shows mostly "good" or "flat" trades

**Characteristics**:
- Consistent positive edge
- Sufficient sample size
- Reliable across different market regimes

### Tier 2 (Promising / Neutral Assets)

**Definition**: Assets under observation, gathering evidence.

**Criteria**:
- Exploration PF between ~0.5 and 1.5, OR
- Exploration trades < 4 (still under-sampled), OR
- Normal PF is mixed (0–1.0) but not catastrophic
- Not clearly Tier 1 or Tier 3

**Characteristics**:
- Neutral or promising but needs more data
- May be trending toward Tier 1 or Tier 3
- Requires patience and continued observation

### Tier 3 (Weak / Avoid Assets)

**Definition**: Underperformers requiring negative tuning or eventual pause.

**Criteria**:
- Exploration PF ~0 or negative with ≥ 5 exploration trades
- Normal PF <= 0.5 if any normal trades exist
- Dream/Debrief consistently labels many "bad" trades
- Repeated failures across diverse regimes

**Characteristics**:
- Consistently weak performance
- Sufficient sample size to conclude underperformance
- May need tighter gates or eventual disable

## Tuning Readiness

### Tier 1: Positive Tuning Eligibility

**When eligible**:
- Exploration trades ≥ 6
- Normal trades ≥ 2
- Exploration PF >= 1.5
- Normal PF >= 1.0

**Allowed adjustments**:
- Slight `conf_min` loosening: -0.02 to -0.05 per cycle
- Slight `exploration_cap` increase: +1 per cycle
- Maximum: -0.1 total `conf_min` adjustment, +2 total cap increase

**Goal**: Gradually increase exposure to proven winners

### Tier 2: Observation Only

**Policy**:
- No structural tuning yet
- Continue exploration
- Gather evidence and wait for more trades or PF stabilization
- Monitor for promotion to Tier 1 or demotion to Tier 3

**Goal**: Build sufficient sample size before making decisions

### Tier 3: Negative Tuning Eligibility

**When eligible**:
- Exploration trades ≥ 7
- Exploration PF <= 0.1 (or negative)
- Normal PF <= 0.5 (if any normal trades exist)

**Allowed adjustments**:
- Slight `conf_min` tightening: +0.02 to +0.05 per cycle
- Slight `exploration_cap` reduction: -1 per cycle
- Maximum: +0.1 total `conf_min` adjustment, -2 total cap decrease

**Goal**: Reduce exposure to underperformers, tighten gates

**Note**: Do NOT promote Tier 3 assets into normal lane. Eventually candidates for pause/disable if performance remains bad.

## Promotion / Demotion Rules

### Promotion to Tier 1

**Requirements**:
- Exploration PF ≥ 1.5
- Exploration trades ≥ 6
- Normal PF ≥ 1.0 with ≥ 2 trades
- No catastrophic "bad" cluster in Dream reviews
- Consistent performance across multiple regimes

**Process**: 
- Reflection assigns Tier 1
- Tuner becomes eligible for positive adjustments
- Monitor closely after promotion

### Demotion to Tier 3

**Requirements**:
- Exploration PF ~0 (or negative) across ≥ 7 trades
- Normal PF ≤ 0.5 if any normal trades exist
- Dream highlights repeated "bad" trades in diverse regimes
- Consistent underperformance despite exploration

**Process**:
- Reflection assigns Tier 3
- Tuner becomes eligible for negative adjustments
- Consider eventual pause/disable if performance doesn't improve

## GPT Tuner Behavior

### When GPT Tuner Should Act

GPT Tuner should only propose:

- **Small, bounded numeric deltas**:
  - `conf_min_delta`: ±0.02 to ±0.05 per cycle
  - `exploration_cap_delta`: ±1 per cycle

- **Based on roadmap thresholds**:
  - Tier 1: Positive tuning only when sample size met
  - Tier 3: Negative tuning only when sample size met
  - Tier 2: No tuning proposals

- **Minimum sample size requirements**:
  - Tier 1 positive: exploration trades ≥ 6, normal trades ≥ 2
  - Tier 3 negative: exploration trades ≥ 7

- **Respect safety limits**:
  - Maximum total `conf_min` adjustment: ±0.1 per symbol
  - Maximum total `exploration_cap` change: ±2 per symbol

### GPT Tuner Output Format

Tuner writes to `reports/gpt/tuner_output.json`:

```json
{
  "tuning_proposals": {
    "ETHUSDT": {
      "conf_min_delta": -0.02,
      "exploration_cap_delta": 1,
      "notes": ["Tier1: Strong performer, eligible for positive tuning"]
    },
    "ATOMUSDT": {
      "conf_min_delta": 0.02,
      "exploration_cap_delta": -1,
      "notes": ["Tier3: Weak performer, negative tuning recommended"]
    }
  }
}
```

## Safety Contract

### All Tuning Changes Must:

1. **Be written to JSON** (`tuner_output.json`):
   - Structured proposals
   - Per-symbol deltas
   - Explanatory notes

2. **Be previewed** (`tuning_preview.json`):
   - Human-readable summary
   - What would change
   - No actual config modifications

3. **Never be applied directly**:
   - No automatic config file changes
   - Requires human review or explicit dry-run approval
   - Shadow mode remains active during tuning

### Current Status

- ✅ **Dry-run only**: All tuning is advisory
- ✅ **Shadow mode**: Real orders blocked
- ✅ **GPT scaffolding**: Ready for integration
- ✅ **Roadmap defined**: Clear thresholds and rules

### Future Integration

When ready to enable GPT Tuner:

1. Replace stub logic in `tools/run_tuner_cycle.py` with GPT calls
2. GPT reads `tuning_rules.yaml` and `reflection_input.json`
3. GPT writes `tuner_output.json` following roadmap rules
4. Human reviews `tuning_preview.json`
5. Optional: Add `--apply` flag to `tools/apply_tuning_proposals.py` (with backups)

## Summary

This roadmap provides:

- **Clear tier definitions** for symbol classification
- **Explicit thresholds** for promotion/demotion
- **Bounded tuning rules** for safe adjustments
- **Safety guarantees** preventing accidental changes
- **Future-ready structure** for GPT integration

All tuning remains **advisory and dry-run** until explicitly enabled with proper safeguards.


