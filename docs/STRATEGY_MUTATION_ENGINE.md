# Strategy Mutation Engine

## Purpose

The Strategy Mutation Engine proposes hypothetical parameter changes for symbols based on their performance, tiers, quality scores, and ARE (Aggregated Research Engine) statistics. These mutations are **proposals only** - they are not automatically applied to configs or live strategies.

## Architecture

### Core Module: `engine_alpha/evolve/mutation_engine.py`

The `MutationCore` class provides:

- **`load_inputs()`**: Loads evolver output, quality scores, and ARE snapshot
- **`propose_mutations()`**: Evaluates all symbols and proposes mutations
- **`save_output()`**: Saves mutations to JSON file

### CLI Tool: `tools/run_mutation_preview.py`

Runs the mutation engine:
- Loads all inputs
- Proposes mutations
- Writes `reports/evolver/mutations.json` and `mutation_preview.json`
- Prints human-readable summary

## Mutation Logic

Mutations are proposed based on:

1. **Tier** (tier1/tier2/tier3) from evolver output
2. **Quality Score** from quality_scores.json
3. **Promotion/Demotion Status** from evolver evaluation
4. **ARE Statistics** for stability checks

### Mutation Rules

#### Promotion Candidates
- **Decrease `entry_conf_min`** by 0.02
- **Increase `exploration_cap`** by 1
- Reason: Strong performance warrants more aggressive exploration

#### Strong Tier1 (quality_score ≥ 70)
- **Decrease `entry_conf_min`** by 0.01
- **Increase `exploration_cap`** by 1
- Reason: Strong performers can handle slightly more opportunities

#### Demotion Candidates
- **Increase `entry_conf_min`** by 0.02
- **Decrease `exploration_cap`** by 1
- Reason: Weak performers need tighter controls

#### Weak Tier3
- **Increase `entry_conf_min`** by 0.02
- **Decrease `exploration_cap`** by 1
- Reason: Reduce risk exposure

#### Promising Tier2 (quality_score ≥ 50)
- **Decrease `entry_conf_min`** by 0.01
- Reason: Cautious relaxation for promising performers

## Output Format

### `reports/evolver/mutations.json`

```json
{
  "generated_at": "2025-12-04T22:00:00+00:00",
  "mutations": {
    "ETHUSDT": [
      {
        "param": "entry_conf_min",
        "delta": -0.01,
        "reason": "Strong performer (quality=88.0): slight relaxation"
      },
      {
        "param": "exploration_cap",
        "delta": 1,
        "reason": "Strong performer: increase exploration capacity"
      }
    ]
  },
  "summary": {
    "total_symbols": 3,
    "total_mutations": 6
  }
}
```

### `reports/evolver/mutation_preview.json`

Same structure as `mutations.json`, written for preview purposes.

## Dry-Run Nature

**IMPORTANT**: The Mutation Engine is **read-only** and **advisory-only**:

- ✅ Reads from evolver output, quality scores, and ARE snapshot
- ✅ Produces mutation proposals
- ❌ Does NOT modify any configs
- ❌ Does NOT change live trading behavior
- ❌ Does NOT make exchange API calls
- ❌ Does NOT move funds
- ✅ Respects SHADOW MODE (all operations are dry-run)

## Future Integration

The mutation system is designed for future enhancement:

1. **Strategy Evolver Integration**: Mutations can be consumed by the Strategy Evolver to create mutated strategy variants
2. **Shadow Mode Testing**: Mutated strategies can be run in shadow mode alongside baseline strategies
3. **Performance Comparison**: Compare mutated strategy performance against baseline
4. **Promotion of Winners**: Automatically promote winning mutations to production (with safety gates)
5. **Strategy Naming**: Integration with `strategy_namer` module to generate names for mutated strategies

## Usage

Run a mutation preview:

```bash
python3 -m tools.run_mutation_preview
```

This will:
1. Load evolver output, quality scores, and ARE snapshot
2. Propose mutations for all symbols
3. Write `reports/evolver/mutations.json` and `mutation_preview.json`
4. Print a summary to stdout

## Dependencies

The Mutation Engine requires:

- `reports/evolver/evolver_output.json` (from `tools/run_evolver_cycle.py`)
- `reports/gpt/quality_scores.json` (from `tools/quality_scores.py`)
- `reports/research/are_snapshot.json` (from `tools/run_are_cycle.py`)

If any of these files are missing, the Mutation Engine will gracefully handle it and proceed with available data.

## Example Output

```
MUTATION PREVIEW
======================================================================

Loading inputs...
   Loaded: 11 symbols from evolver
   Loaded: 11 quality scores
   Loaded: 11 ARE symbols

Proposing mutations...
✅ Mutations written to: /root/Chloe-alpha/reports/evolver/mutations.json
✅ Preview written to: /root/Chloe-alpha/reports/evolver/mutation_preview.json

MUTATION SUMMARY
----------------------------------------------------------------------

ETHUSDT:
  • Decrease entry_conf_min by -0.010 (reason: Strong performer (quality=88.0): slight relaxation)
  • Increase exploration_cap by +1 (reason: Strong performer: increase exploration capacity)

DOTUSDT:
  • Decrease entry_conf_min by -0.010 (reason: Strong performer (quality=85.0): slight relaxation)
  • Increase exploration_cap by +1 (reason: Strong performer: increase exploration capacity)

======================================================================
Note: All mutations are PROPOSALS ONLY. No configs were modified.
======================================================================
```


