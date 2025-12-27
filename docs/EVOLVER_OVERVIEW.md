# Evolver Overview

## Purpose

The Evolver is a tier-based evaluation system that analyzes symbol performance across multiple dimensions to produce **advisory** promotion and demotion suggestions. It combines:

- **Tiers** from GPT Reflection (`reflection_output.json`)
- **Quality Scores** (`quality_scores.json`)
- **ARE (Aggregated Research Engine)** multi-horizon stats (`are_snapshot.json`)
- **Promotion/Demotion Rules** from `config/tuning_rules.yaml`

## Architecture

### Core Module: `engine_alpha/evolve/evolver_core.py`

The evolver core provides three main functions:

1. **`load_inputs()`**: Aggregates metrics from multiple sources into a per-symbol metrics dictionary
2. **`evaluate_symbol(symbol, metrics)`**: Evaluates a single symbol for promotion/demotion eligibility
3. **`evolve_all_symbols(metrics_dict)`**: Evaluates all symbols and produces complete output

### CLI Tool: `tools/run_evolver_cycle.py`

Orchestrates a single Evolver pass:
- Loads inputs
- Evaluates all symbols
- Writes `reports/evolver/evolver_output.json`
- Prints human-readable summary

## Evaluation Logic

### Promotion (Tier2 → Tier1)

A symbol is flagged as a promotion candidate if it meets **all** of these criteria:

- **Exploration PF** ≥ threshold (default: 1.5)
- **Exploration trades** ≥ threshold (default: 6)
- **Normal PF** ≥ threshold (default: 1.0)
- **Normal trades** ≥ threshold (default: 2)
- **Quality score** ≥ 70 (if available)

### Demotion (Tier2 → Tier3 or Tier1 → Tier2)

A symbol is flagged as a demotion candidate if it meets **all** of these criteria:

- **Exploration PF** ≤ threshold (default: 0.0)
- **Exploration trades** ≥ threshold (default: 7)
- **Normal PF** ≤ threshold (default: 0.5)

### Stability Checks

The evolver also checks for spiky performance:
- If short-term PF is high (>2.0) but long-term PF is weak (<1.0), the symbol is **not** promoted
- This prevents promoting symbols with unsustainable short-term spikes

## Output Format

The evolver writes `reports/evolver/evolver_output.json` with this structure:

```json
{
  "generated_at": "2025-12-04T21:00:00+00:00",
  "symbols": {
    "ETHUSDT": {
      "symbol": "ETHUSDT",
      "tier": "tier1",
      "promotion_candidate": false,
      "demotion_candidate": false,
      "suggested_conf_min_delta": 0.0,
      "suggested_exploration_cap_delta": 0,
      "notes": ["No tier change recommended at this time"]
    },
    ...
  },
  "summary": [
    "ETHUSDT: tier1, no change",
    "DOTUSDT: tier2, promotion_candidate=true (flagged for promotion)",
    ...
  ]
}
```

## Advisory-Only Operation

**IMPORTANT**: The Evolver is **read-only** and **advisory-only**:

- ✅ Reads from existing reports and configs
- ✅ Produces advisory suggestions
- ❌ Does NOT modify any configs
- ❌ Does NOT change live trading behavior
- ❌ Does NOT make exchange API calls
- ❌ Does NOT move funds

## Integration with Other Systems

### GPT Reflection

The Evolver reads tiers assigned by GPT Reflection. These tiers are the starting point for evaluation.

### GPT Tuner

The Evolver's suggestions (`suggested_conf_min_delta`, `suggested_exploration_cap_delta`) can be consumed by GPT Tuner to propose actual config changes (still in dry-run mode).

### Human Review

The `evolver_output.json` file is designed to be human-readable and can be reviewed before any manual config changes are applied.

## Future Enhancements

Potential future enhancements:

1. **Automatic Application**: A future phase may allow automatic tier updates (with safety gates)
2. **Multi-Symbol Correlation**: Evaluate symbol relationships and portfolio-level effects
3. **Time-Based Rules**: Require symbols to maintain criteria for N days before promotion
4. **Dream Label Integration**: Incorporate Dream scenario labels into promotion/demotion logic

## Usage

Run a single Evolver cycle:

```bash
python3 -m tools.run_evolver_cycle
```

This will:
1. Load all input files
2. Evaluate all symbols
3. Write `reports/evolver/evolver_output.json`
4. Print a summary to stdout

## Dependencies

The Evolver requires:

- `reports/gpt/reflection_output.json` (from GPT Reflection cycle)
- `reports/gpt/quality_scores.json` (from `tools/quality_scores.py`)
- `reports/research/are_snapshot.json` (from `tools/run_are_cycle.py`)
- `config/tuning_rules.yaml` (for promotion/demotion thresholds)

If any of these files are missing, the Evolver will gracefully handle it and use defaults where appropriate.


