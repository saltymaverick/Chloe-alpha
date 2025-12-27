# Meta-Reasoner

## Overview

The Meta-Reasoner is the "AI supervisor" that inspects GPT outputs across time to detect contradictions, instability, and bad suggestions. It provides high-level diagnostics and recommendations.

## Architecture

### Analysis Types

The Meta-Reasoner detects three types of issues:

1. **Tier Instability**: Symbols that bounce between tier1/tier2/tier3 across cycles
   - Example: ETH moved between tier1 and tier2 in 3 of last 5 cycles

2. **Contradictory Tuning**: Tuning proposals that flip direction repeatedly
   - Example: Tuner proposals for DOT alternated between loosening (+0.02) and tightening (-0.02)

3. **Reflection-Tuner Disagreement**: Reflection says symbol is strong but Tuner proposes tightening (or vice versa)
   - Example: Reflection assigned tier1 (strong) but Tuner proposes tightening

### Output

The Meta-Reasoner writes a report to `reports/research/meta_reasoner_report.json`:

```json
{
  "ts": "...",
  "issues": [
    {
      "type": "tier_instability",
      "symbol": "SOLUSDT",
      "details": "Symbol moved between tier2 and tier3 in 3 of last 5 cycles.",
      "tier_history": ["tier2", "tier3", "tier2", "tier3"]
    }
  ],
  "recommendations": [
    "Reduce tuning frequency for SOLUSDT until tiers stabilize.",
    "Require stronger evidence before tuning DOTUSDT."
  ],
  "memory_entries_analyzed": 5,
  "issue_count_by_type": {
    "tier_instability": 1,
    "contradictory_tuning": 0,
    "reflection_tuner_disagreement": 0
  }
}
```

## Usage

### Running Analysis

```bash
python3 -m tools.run_meta_review
```

This analyzes the last 5 memory entries and prints a summary.

### API

```python
from engine_alpha.research.meta_reasoner import analyze

# Analyze last 5 memory entries
report = analyze(n=5)

# Access issues and recommendations
issues = report["issues"]
recommendations = report["recommendations"]
```

## Integration

The Meta-Reasoner is designed to run:

1. **After research cycles**: After Reflection/Tuner/Dream cycles complete
2. **Before applying tuning**: Review meta-reasoner report before applying tuning proposals
3. **As part of nightly orchestrator**: Include in nightly research pipeline

## Recommendations

The Meta-Reasoner generates actionable recommendations:

- **Tier Instability**: "Reduce tuning frequency for SYMBOL until tiers stabilize."
- **Contradictory Tuning**: "Require stronger evidence before tuning SYMBOL."
- **Disagreements**: "Review Reflection and Tuner logic for SYMBOL - they disagree on symbol strength."

## Safety

- **Advisory-only**: Meta-Reasoner does not automatically modify configs or tuning
- **Read-only**: Only reads memory entries, never modifies them
- **Bounded**: Analyzes only last N entries (default: 5) to focus on recent patterns
- **Non-blocking**: Issues are warnings, not hard blocks

## Benefits

1. **Consistency**: Detects when GPT outputs are inconsistent across cycles
2. **Quality Control**: Flags noisy or unreliable tuning proposals
3. **Pattern Detection**: Identifies symbols that need more data before tuning
4. **Transparency**: Provides clear explanations for detected issues

