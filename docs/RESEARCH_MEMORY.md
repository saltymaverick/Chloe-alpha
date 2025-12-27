# Research Memory Layer

## Overview

The Research Memory Layer provides persistent storage for GPT outputs (Reflection, Tuner, Dream) and research data (ARE, Quality Scores, Drift Reports). This allows GPT to see its own past opinions and be more consistent across cycles.

## Architecture

### Storage

- **Location**: `reports/research/research_memory.jsonl`
- **Format**: JSONL (one JSON object per line)
- **Structure**: Each entry contains:
  - `ts`: ISO timestamp
  - `reflection`: Reflection output JSON (if available)
  - `tuner`: Tuner output JSON (if available)
  - `dream`: Dream output JSON (if available)
  - `quality_scores`: Quality scores JSON (if available)
  - `drift`: Drift report JSON (if available)
  - `are`: ARE snapshot JSON (if available)

### Usage

#### Taking Snapshots

```bash
python3 -m tools.run_memory_snapshot
```

This captures current state of all GPT outputs and research data.

#### Loading Memory in GPT Cycles

Memory can be optionally loaded in Reflection/Tuner/Dream cycles via environment flags:

- `USE_GPT_REFLECTION_MEMORY=true` (default: false)
- `USE_GPT_TUNER_MEMORY=true` (default: false)
- `USE_GPT_DREAM_MEMORY=true` (default: false)

When enabled, cycles load the last N memory entries (default: 3) and include them in GPT input payloads under `memory_context`.

#### API

```python
from engine_alpha.research.research_memory import take_snapshot, load_recent_memory

# Take a snapshot
snapshot = take_snapshot()

# Load last 3 memory entries
memory = load_recent_memory(n=3)
```

## Benefits

1. **Consistency**: GPT can see its past judgments and avoid flip-flopping
2. **Context**: GPT understands how its opinions have evolved over time
3. **Pattern Detection**: Enables detection of persistent issues across cycles
4. **Bounded**: Memory is bounded (only last N entries loaded) to prevent context bloat

## Safety

- **Read-only**: Memory is never automatically modified by GPT cycles
- **Advisory-only**: Memory does not affect live trading behavior
- **Bounded**: Only last N entries are loaded (default: 3) to prevent context bloat
- **Optional**: Memory is opt-in via environment flags

## Integration with Cycles

When memory flags are enabled, GPT input payloads include:

```json
{
  "symbols": {...},
  "are": {...},
  "quality_scores": {...},
  "memory_context": [
    {
      "ts": "...",
      "reflection": {...},
      "tuner": {...},
      "drift": {...}
    },
    ...
  ]
}
```

GPT can then reference past judgments in its analysis.

