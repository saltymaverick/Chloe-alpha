# Symbol Edge Profiler (PSOE)

## Overview

The Symbol Edge Profiler is a **Hybrid Per-Symbol Optimization Engine (PSOE)** that computes hard-quant edge profiles for each trading symbol. It classifies symbols into archetypes based on PF, drift, microstructure, execution quality, and self-eval history, enabling symbol-specific tuning recommendations.

## Purpose

- **Quant Backbone**: Computes objective metrics per symbol (PF, drift, microstructure, execution quality)
- **Archetype Classification**: Categorizes symbols into types (trend_monster, fragile, mean_reverter, etc.)
- **GPT Integration**: Exposes profiles to GPT Tuner v4 and Reflection v4 for intelligent, symbol-specific tuning
- **Advisory-Only**: All outputs remain advisory-only and PAPER-only in this phase

## Output Location

**File:** `reports/research/symbol_edge_profile.json`

**Structure:**
```json
{
  "generated_at": "2025-12-05T02:00:00Z",
  "profiles": {
    "ETHUSDT": {
      "tier": "tier1",
      "short_pf": 2.15,
      "long_pf": 1.89,
      "drift": "improving",
      "micro_regime": "clean_trend",
      "exec_label": "friendly",
      "quality_score": 85.0,
      "rotation": "overweight",
      "self_eval": {
        "improved": 3,
        "degraded": 0,
        "inconclusive": 1
      },
      "archetype": "trend_monster"
    },
    ...
  }
}
```

## Archetypes

### trend_monster
- **Criteria**: High PF (>2.0), friendly execution, clean microstructure
- **Tuning**: Allow slightly looser confidence thresholds (conf_min_delta = -0.01 to -0.02)
- **Example**: ETHUSDT, BTCUSDT

### fragile
- **Criteria**: Low PF (<0.8), hostile execution, choppy microstructure
- **Tuning**: Avoid loosening, consider tightening (conf_min_delta = +0.01 to +0.02)
- **Example**: DOGEUSDT, ADAUSDT

### mean_reverter
- **Criteria**: Moderate PF (0.5-1.5), hostile execution, indecision/chop microstructure
- **Tuning**: Be cautious with loosening; these symbols need strict gates
- **Example**: LINKUSDT, ATOMUSDT

### neutral_trender
- **Criteria**: Decent PF (≥1.0), neutral execution
- **Tuning**: Standard tuning bounds apply
- **Example**: DOTUSDT, BNBUSDT

### strong_but_choppy
- **Criteria**: High PF (>1.5) but hostile execution/microstructure
- **Tuning**: Moderate loosening acceptable, but watch microstructure
- **Example**: SOLUSDT (in certain regimes)

### weak_but_improving
- **Criteria**: Low PF (<1.0) but improving drift, non-hostile execution
- **Tuning**: Cautious loosening may be appropriate as drift improves
- **Example**: XRPUSDT (during recovery phases)

### unknown
- **Criteria**: Insufficient data or mixed signals
- **Tuning**: Default to conservative bounds

## Input Sources

The profiler reads from:

1. **ARE Snapshot** (`reports/research/are_snapshot.json`)
   - Short/long horizon PF per symbol

2. **Drift Report** (`reports/research/drift_report.json`)
   - Drift status (improving/stable/degrading) per symbol

3. **Microstructure Snapshot** (`reports/research/microstructure_snapshot_15m.json`)
   - Micro-regime classification per symbol

4. **Execution Quality** (`reports/research/execution_quality.json`)
   - Execution label (friendly/neutral/hostile) per symbol

5. **Quality Scores** (`reports/gpt/quality_scores.json`)
   - Quality score per symbol

6. **Reflection Output** (`reports/gpt/reflection_output.json`)
   - Tier assignments per symbol

7. **Tuning Self-Eval** (`reports/research/tuning_self_eval.json`) [optional]
   - Self-eval summary (improved/degraded/inconclusive counts)

8. **Auto-Rotation Recs** (`reports/research/auto_rotation_recs.json`) [optional]
   - Rotation recommendations (overweight/underweight/hold)

## Usage

### Manual Run

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

python3 -m tools.run_symbol_edge_profile
```

### Automated Run

The profiler runs automatically as part of the nightly research cycle:

```bash
python3 -m tools.nightly_research_cycle
```

It runs after ExecutionQuality, NormalLaneOptimizer, and AutoRotation, and before Reflection/Tuner/Dream cycles.

### View in Dashboard

```bash
python3 -m tools.intel_dashboard
```

The dashboard shows a "SYMBOL EDGE PROFILES" section with archetype, PF, drift, execution quality, and quality scores per symbol.

## GPT Tuner v4 Integration

The symbol edge profiles are automatically included in GPT Tuner v4 input payloads:

- **Field**: `symbol_edge_profiles` in `tuner_input.json`
- **Usage**: GPT Tuner v4 uses archetypes to tailor tuning recommendations per symbol
- **Bounds**: All tuning deltas remain within safe bounds (conf_min_delta: [-0.02, +0.02], exploration_cap_delta: [-1, +1])

### Example GPT Reasoning

For a `trend_monster` symbol with friendly execution:
- "ETHUSDT is classified as trend_monster with friendly execution. Allow slight loosening: conf_min_delta = -0.01"

For a `fragile` symbol with hostile execution:
- "DOGEUSDT is classified as fragile with hostile execution. Avoid loosening, consider tightening: conf_min_delta = +0.01"

## Safety Guarantees

- **Advisory-Only**: All outputs are recommendations, not auto-applied
- **PAPER-Only**: No live trading behavior changes
- **Bounded**: All tuning deltas remain within safe bounds
- **Self-Eval Gating**: Symbols with harmful tuning history are automatically frozen
- **No Config Writes**: Profiles do not modify core config files

## Future Enhancements

- **Exit Logic Tuning**: Per-symbol exit thresholds based on archetype
- **Position Sizing**: Archetype-based position sizing adjustments
- **Regime-Specific Profiles**: Separate profiles for different market regimes
- **Dynamic Archetype Updates**: Real-time archetype reclassification as data accumulates

## Related Documentation

- `docs/ADVANCED_RESEARCH.md` - Advanced research components
- `docs/EXECUTION_QUALITY.md` - Execution quality analyzer
- `docs/AUTO_ROTATION.md` - Auto-rotation engine
- `docs/TUNING_SELF_EVAL.md` - Tuning self-evaluation
- `docs/GPT_FLAGS.md` - GPT-related environment flags

