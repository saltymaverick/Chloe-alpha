# Strategy Mutation Overview

## Purpose

The Strategy Mutation Engine proposes hypothetical parameter changes for symbols based on their performance, tiers, and quality scores. These mutations are **proposals only** - they are not automatically applied to configs or live strategies.

## Architecture

### Core Module: `engine_alpha/evolve/mutation_engine.py`

The mutation engine provides two main functions:

1. **`propose_mutations_for_symbol(symbol, evolver_evaluation, quality_score)`**: 
   - Evaluates a single symbol and proposes mutations based on:
     - Tier (tier1/tier2/tier3)
     - Promotion/demotion candidate status
     - Quality score
   - Returns a list of mutation proposals

2. **`propose_all_mutations(evolver_output, quality_scores)`**:
   - Evaluates all symbols and returns a dict mapping symbol -> list of mutations

### CLI Tool: `tools/run_mutation_preview.py`

Runs the mutation engine in preview mode:
- Loads evolver output and quality scores
- Proposes mutations for all symbols
- Writes `reports/evolver/strategy_mutations.jsonl`
- Prints human-readable summary

## Mutation Logic

### Promotion Candidates (Tier2 → Tier1)

For symbols flagged as promotion candidates:
- **Decrease `entry_conf_min`** by suggested delta (typically -0.02)
- **Increase `exploration_cap`** by suggested delta (typically +1)
- Reason: Strong and stable performance warrants more aggressive exploration

### Strong Tier1 Symbols

For Tier1 symbols with quality_score ≥ 70:
- **Decrease `entry_conf_min`** by 0.01 (slight relaxation)
- **Increase `exploration_cap`** by 1
- Reason: Strong performers can handle slightly more opportunities

### Demotion Candidates

For symbols flagged as demotion candidates:
- **Increase `entry_conf_min`** by suggested delta (typically +0.02)
- **Decrease `exploration_cap`** by suggested delta (typically -1)
- Reason: Weak performers need tighter controls

### Weak Tier3 Symbols

For Tier3 symbols:
- **Increase `entry_conf_min`** by 0.02 (tighter entry criteria)
- **Decrease `exploration_cap`** by 1
- Reason: Reduce risk exposure for weak performers

### Promising Tier2 Symbols

For Tier2 symbols with quality_score ≥ 50:
- **Decrease `entry_conf_min`** by 0.01 (cautious relaxation)
- Reason: Promising performers deserve slight opportunity increase

## Output Format

### JSONL File: `reports/evolver/strategy_mutations.jsonl`

Each line is a JSON object:

```json
{
  "symbol": "ETHUSDT",
  "param": "entry_conf_min",
  "delta": -0.02,
  "reason": "Strong performer (quality_score=88.0): slight relaxation for more opportunities",
  "generated_at": 1701720000.0
}
```

### Console Output

The CLI tool prints a human-readable summary:

```
MUTATION PREVIEW
======================================================================

ETHUSDT:
  • Decrease entry_conf_min by -0.010 (reason: Strong performer (quality_score=88.0): slight relaxation for more opportunities)
  • Increase exploration_cap by +1 (reason: Strong performer: increase exploration capacity)

DOTUSDT:
  • Decrease entry_conf_min by -0.010 (reason: Strong performer (quality_score=85.0): slight relaxation for more opportunities)
  • Increase exploration_cap by +1 (reason: Strong performer: increase exploration capacity)
```

## Advisory-Only Operation

**IMPORTANT**: The Mutation Engine is **read-only** and **advisory-only**:

- ✅ Reads from evolver output and quality scores
- ✅ Produces mutation proposals
- ❌ Does NOT modify any configs
- ❌ Does NOT change live trading behavior
- ❌ Does NOT make exchange API calls
- ❌ Does NOT move funds

## Future Plan

The mutation system is designed for future enhancement:

1. **Shadow Mode Testing**: Mutated strategies can be run in shadow mode alongside baseline strategies
2. **Performance Comparison**: Compare mutated strategy performance against baseline
3. **Promotion of Winners**: Automatically promote winning mutations to production (with safety gates)
4. **Strategy Naming**: Integration with `strategy_namer` module to generate names for mutated strategies

## Integration with Other Systems

### Evolver

The Mutation Engine consumes output from the Evolver (`evolver_output.json`), which provides:
- Tier assignments
- Promotion/demotion candidate flags
- Suggested tuning deltas

### Quality Scores

The Mutation Engine uses quality scores to refine mutation proposals, especially for Tier1 and Tier2 symbols.

### GPT Tuner

The Mutation Engine's proposals can be consumed by GPT Tuner to propose actual config changes (still in dry-run mode).

## Usage

Run a mutation preview:

```bash
python3 -m tools.run_mutation_preview
```

This will:
1. Load evolver output and quality scores
2. Propose mutations for all symbols
3. Write `reports/evolver/strategy_mutations.jsonl`
4. Print a summary to stdout

## Dependencies

The Mutation Engine requires:

- `reports/evolver/evolver_output.json` (from `tools/run_evolver_cycle.py`)
- `reports/gpt/quality_scores.json` (from `tools/quality_scores.py`)

If any of these files are missing, the Mutation Engine will gracefully handle it and proceed with available data.

## Example Scenarios

### Scenario 1: Strong Tier1 Symbol (ETHUSDT)

**Input:**
- Tier: tier1
- Quality score: 88.0
- Promotion candidate: false

**Mutations Proposed:**
- Decrease `entry_conf_min` by 0.01
- Increase `exploration_cap` by 1

**Reason:** Strong performer can handle slightly more opportunities

### Scenario 2: Promotion Candidate (DOTUSDT)

**Input:**
- Tier: tier2
- Promotion candidate: true
- Suggested conf_min_delta: -0.02
- Suggested exploration_cap_delta: +1

**Mutations Proposed:**
- Decrease `entry_conf_min` by 0.02
- Increase `exploration_cap` by 1

**Reason:** Promotion candidate warrants more aggressive exploration

### Scenario 3: Weak Tier3 Symbol (ATOMUSDT)

**Input:**
- Tier: tier3
- Quality score: 12.0

**Mutations Proposed:**
- Increase `entry_conf_min` by 0.02
- Decrease `exploration_cap` by 1

**Reason:** Weak performer needs tighter controls to reduce risk


