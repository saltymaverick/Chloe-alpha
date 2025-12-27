# Strategy Variant Runner

## Overview

The **Strategy Variant Runner** allows Chloe to run multiple strategy variants in parallel, testing mutations safely without affecting the main trading loop.

## Purpose

The Variant Runner enables:
- **Parallel strategy testing**: Run multiple mutation strategies simultaneously
- **Isolated execution**: Each variant runs independently with its own state
- **Safe experimentation**: No impact on main trading loop or configs
- **Performance tracking**: Each variant logs its own performance separately

## Architecture

### Components

1. **Variant Runner** (`engine_alpha/variant/variant_runner.py`)
   - Core execution engine for variant strategies
   - Simulates trades using mutated thresholds
   - Maintains isolated state per variant

2. **Variant Cycle Tool** (`tools/run_variant_cycle.py`)
   - CLI tool to run one cycle of variant execution
   - Prints summary of variant performance

3. **Nightly Integration**
   - Variant cycle runs automatically in nightly research cycle
   - Executes after Memory Snapshot and Meta Review

## Key Differences

### Main Strategy
- **Real trading logic**: Uses actual configs and thresholds
- **Live positions**: Affects real position manager
- **Real trades**: Logs to `reports/trades.jsonl`

### Exploration Lane
- **Small risk**: Limited exploration trades
- **Same thresholds**: Uses main strategy thresholds
- **Real execution**: Actually executes trades (with small size)

### Variant Runner
- **Parallel simulation**: Runs multiple variants simultaneously
- **Mutated thresholds**: Each variant uses different thresholds
- **Isolated state**: No interaction with main positions
- **Simulated trades**: Logs to `reports/variant/<variant_id>_trades.jsonl`

## File Locations

### Input
- **Mutation strategies**: `reports/evolver/mutation_strategies.jsonl`
  - Created by `tools/create_mutation_shadows.py`
  - Contains shadow strategy definitions

### Output
- **Variant logs**: `reports/variant/<variant_id>_trades.jsonl`
  - Trade-by-trade log for each variant
  - Format: JSONL (one trade per line)

- **Variant summaries**: `reports/variant/<variant_id>_summary.json`
  - Current state and stats for each variant
  - Updated after each cycle

## Variant State Structure

Each variant maintains:
```json
{
  "variant_id": "ETH_main_mut_0001",
  "symbol": "ETHUSDT",
  "mutations": {
    "conf_min_delta": -0.02,
    "exploration_cap_delta": 1
  },
  "position": {
    "dir": 0,
    "entry_px": null,
    "bars_open": 0
  },
  "stats": {
    "exp_trades": 5,
    "exp_pf": 1.25,
    "norm_trades": 0,
    "norm_pf": null,
    "total_pnl": 0.05,
    "wins": 3,
    "losses": 2
  }
}
```

## Execution Flow

1. **Load Variants**
   - Read `mutation_strategies.jsonl`
   - Filter for `status="shadow"`

2. **Initialize States**
   - Load existing state from summary files
   - Create new state if variant is new

3. **Simulate Step**
   - For each variant:
     - Get latest candle
     - Compute signals
     - Apply mutated thresholds
     - Make entry/exit decisions
     - Update variant state

4. **Save Results**
   - Append trades to variant log
   - Update variant summary

## Mutated Thresholds

Variants apply mutations to base thresholds:

```python
mutated_threshold = base_threshold + conf_min_delta
mutated_exploration_cap = base_exploration_cap + exploration_cap_delta
```

Example:
- Base threshold (trend): 0.70
- Mutation: `conf_min_delta: -0.02`
- Variant threshold: 0.68

## Usage

### Manual Execution
```bash
python3 -m tools.run_variant_cycle
```

### Automatic Execution
Variant cycle runs automatically in nightly research cycle:
```bash
python3 -m tools.nightly_research_cycle
```

## Future Integration

### Promotion Engine
The Evolver may eventually:
1. Compare variant performance vs base strategy
2. Propose promotion of successful variants
3. Require human approval before promotion
4. Replace main strategy with promoted variant (still paper-only)

### Multi-Strategy Runner
Future enhancement:
- Run variants in true parallel (not sequential)
- Support multiple symbols per variant
- Real-time performance comparison dashboard

## Safety Guarantees

✅ **No config writes**: Variants never modify config files  
✅ **No live orders**: All execution is simulated  
✅ **No position interference**: Variants don't touch main positions  
✅ **Shadow mode**: Respects shadow mode settings  
✅ **Advisory only**: All mutations remain proposals until promotion

## Current Limitations

- **Sequential execution**: Variants run one at a time (not parallel)
- **Single symbol**: Each variant trades one symbol
- **Exploration-only**: Variants only simulate exploration lane
- **No promotion**: No automatic promotion to main strategy yet

## Related Documentation

- [Mutation Shadow Strategies](./MUTATION_SHADOW_STRATEGIES.md)
- [Evolver Core](./docs/EVOLVER.md)
- [Nightly Orchestrator](./NIGHTLY_ORCHESTRATOR.md)

