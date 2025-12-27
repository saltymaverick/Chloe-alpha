# GPT Mind Stack - Complete System

## Overview

Chloe now has a complete GPT "mind stack" with three interconnected layers:

1. **Reflection**: Analyzes trading activity and assigns tiers
2. **Tuner**: Proposes small, safe threshold adjustments
3. **Dream/Replay**: Replays interesting trades and evaluates scenarios

**All tools are DRY-RUN** - no live configs are modified.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    GPT Mind Stack                        │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  1. REFLECTION                                           │
│     build_reflection_snapshot                            │
│     → reflection_input.json                               │
│     run_reflection_cycle                                  │
│     → reflection_output.json (tiers, insights)           │
│                                                           │
│  2. TUNER                                                 │
│     build_tuner_input                                     │
│     → tuner_input.json                                    │
│     run_tuner_cycle                                       │
│     → tuner_output.json (proposals)                       │
│     apply_tuning_proposals                                │
│     → tuning_preview.json                                 │
│                                                           │
│  3. DREAM/REPLAY                                          │
│     build_dream_input                                     │
│     → dream_input.json (scenarios)                        │
│     run_dream_cycle                                       │
│     → dream_output.json (reviews)                         │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Pipeline Flow

### Reflection Layer
```bash
python3 -m tools.build_reflection_snapshot
python3 -m tools.run_reflection_cycle
```
- Aggregates trades, X-ray, positions
- Assigns symbol tiers (tier1/tier2/tier3)
- Produces reflection insights

### Tuner Layer
```bash
python3 -m tools.build_tuner_input
python3 -m tools.run_tuner_cycle
python3 -m tools.apply_tuning_proposals
```
- Merges reflection + stats + gates
- Proposes confidence/cap deltas
- Shows preview (dry-run)

### Dream/Replay Layer
```bash
python3 -m tools.build_dream_input
python3 -m tools.run_dream_cycle
```
- Selects interesting trade scenarios
- Replays trades with proposed changes
- Labels scenarios (good/bad/flat)

## Quick Start

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Run full mind stack
python3 -m tools.run_dream_cycle

# Or run individual layers
python3 -m tools.run_reflection_cycle
python3 -m tools.run_tuner_cycle
python3 -m tools.run_dream_cycle
```

## File Descriptions

### Reflection Files
- **reflection_input.json**: Raw stats (trades, X-ray, positions, gates)
- **reflection_output.json**: Tiers, comments, suggested actions

### Tuner Files
- **tuner_input.json**: Combined view (stats + reflection + gates)
- **tuner_output.json**: Tuning proposals (deltas per symbol)
- **tuning_preview.json**: Human-readable preview

### Dream Files
- **dream_input.json**: Selected scenarios + combined context
- **dream_output.json**: Scenario reviews (labels, notes)

## Scenario Selection

Dream input selects interesting trades:
- Worst 10 exploration losers
- Best 10 exploration winners
- A few normal trades (good and bad)

Each scenario includes:
- Trade metadata (symbol, time, pct, kind, regime)
- Symbol context (tier, stats, gates, proposals)
- Reflection insights

## Current Status

✅ **Complete**: All mind stack tools implemented
✅ **Dry-run**: No configs modified
✅ **Stub logic**: Simple classification and proposals
⏳ **Future**: Replace stubs with GPT calls

## Next Steps (Future)

1. **Replace stub reflection**:
   - `run_reflection_cycle.py` → call GPT with reflection_input.json
   - GPT writes reflection_output.json

2. **Replace stub tuner**:
   - `run_tuner_cycle.py` → call GPT with tuner_input.json
   - GPT writes tuner_output.json

3. **Replace stub dream**:
   - `run_dream_cycle.py` → call GPT with dream_input.json
   - GPT writes dream_output.json with rich scenario analysis

4. **Add apply mode** (optional):
   - `apply_tuning_proposals.py --apply` → actually modify configs
   - Always create backups and diffs

## Safety Features

- ✅ All tools are read-only (dry-run)
- ✅ No config files modified
- ✅ No trading behavior changed
- ✅ Stub proposals are tiny and safe
- ✅ Full pipeline can be run anytime

## Example Output

```
✅ Dream cycle complete.
   Input : reports/gpt/dream_input.json
   Output: reports/gpt/dream_output.json
   Reviewed 25 scenarios

Scenario 1:
  Symbol: ETHUSDT
  Time: 2025-01-15T10:00:00Z
  PnL: -0.0150
  Kind: exploration
  Label: bad
  Notes:
    - Trade lost more than 1%.
    - Tier at time of analysis: tier1
    - Trade kind: exploration
    - Regime: trend_down
```

## Files Created

### Reflection Layer
- `tools/build_reflection_snapshot.py`
- `tools/run_reflection_cycle.py`

### Tuner Layer
- `tools/build_tuner_input.py`
- `tools/run_tuner_cycle.py`
- `tools/apply_tuning_proposals.py`

### Dream/Replay Layer
- `tools/build_dream_input.py`
- `tools/run_dream_cycle.py`

### Documentation
- `docs/GPT_SCAFFOLDING.md`
- `docs/GPT_MIND_STACK.md` (this file)

All tools follow Chloe's existing patterns and are ready for GPT integration.
