# GPT Scaffolding System - Complete Pipeline

## Overview

Chloe now has a complete GPT scaffolding system that provides:
- **Reflection**: Analyzes trading activity and assigns tiers
- **Tuning**: Proposes small, safe threshold adjustments
- **Preview**: Shows what would change (dry-run only)

**All tools are DRY-RUN** - no live configs are modified.

## Pipeline Flow

```
1. build_reflection_snapshot
   → reports/gpt/reflection_input.json
   (Raw stats: trades, X-ray, positions)

2. run_reflection_cycle
   → reports/gpt/reflection_output.json
   (Reflection insights: tiers, comments, actions)

3. build_tuner_input
   → reports/gpt/tuner_input.json
   (Combined view: stats + reflection + gates)

4. run_tuner_cycle
   → reports/gpt/tuner_output.json
   (Tuning proposals: deltas per symbol)

5. apply_tuning_proposals
   → reports/gpt/tuning_preview.json
   (Human-readable preview)
```

## Quick Start

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Run full pipeline
python3 -m tools.run_tuner_cycle
python3 -m tools.apply_tuning_proposals

# Or run individual steps
python3 -m tools.build_reflection_snapshot
python3 -m tools.run_reflection_cycle
python3 -m tools.build_tuner_input
python3 -m tools.run_tuner_cycle
python3 -m tools.apply_tuning_proposals
```

## File Descriptions

### reflection_input.json
- **Source**: `build_reflection_snapshot.py`
- **Content**: Raw statistics per symbol
  - Exploration vs normal trades/PF
  - Gate behavior stats
  - Recent trades
  - Open positions
- **Used by**: Reflection GPT (future)

### reflection_output.json
- **Source**: `run_reflection_cycle.py` (stub now, GPT later)
- **Content**: Reflection insights
  - Symbol tiers (tier1/tier2/tier3)
  - Per-symbol comments
  - Suggested actions
- **Used by**: Tuner GPT

### tuner_input.json
- **Source**: `build_tuner_input.py`
- **Content**: Combined view for tuning
  - Stats + reflection + gates per symbol
  - Current tiers
  - Open positions
- **Used by**: Tuner GPT

### tuner_output.json
- **Source**: `run_tuner_cycle.py` (stub now, GPT later)
- **Content**: Tuning proposals
  - `conf_min_delta` per symbol
  - `exploration_cap_delta` per symbol
  - Notes explaining proposals
- **Used by**: `apply_tuning_proposals.py`

### tuning_preview.json
- **Source**: `apply_tuning_proposals.py`
- **Content**: Human-readable preview
  - Same as tuner_output but formatted for inspection
- **Used by**: Operator review, future apply tool

## Current Status

✅ **Complete**: All scaffolding tools implemented
✅ **Dry-run**: No configs modified
✅ **Stub logic**: Simple tier assignment and proposals
⏳ **Future**: Replace stubs with GPT calls

## Next Steps (Future)

1. **Replace stub reflection**:
   - `run_reflection_cycle.py` → call GPT with reflection_input.json
   - GPT writes reflection_output.json

2. **Replace stub tuner**:
   - `run_tuner_cycle.py` → call GPT with tuner_input.json
   - GPT writes tuner_output.json

3. **Add apply mode** (optional):
   - `apply_tuning_proposals.py --apply` → actually modify configs
   - Always create backups and diffs
   - Require explicit confirmation

## Safety Features

- ✅ All tools are read-only (dry-run)
- ✅ No config files modified
- ✅ No trading behavior changed
- ✅ Stub proposals are tiny and safe
- ✅ Full pipeline can be run anytime

## Example Output

```
CHLOE TUNING PREVIEW (DRY-RUN)
------------------------------

Symbol: ATOMUSDT
  Proposed conf_min delta       : +0.0200
  Proposed exploration cap delta: -1
  Notes:
    - Stub: symbol is tier3 with enough exploration sample; 
            slightly tighten confidence and reduce exploration cap.

✅ Tuning preview written to: reports/gpt/tuning_preview.json
   This is still a DRY RUN. No live configs were changed.
```

## Files Created

- `tools/build_reflection_snapshot.py`
- `tools/run_reflection_cycle.py`
- `tools/build_tuner_input.py`
- `tools/run_tuner_cycle.py`
- `tools/apply_tuning_proposals.py`
- `docs/GPT_SCAFFOLDING.md` (this file)

All tools follow Chloe's existing patterns and are ready for GPT integration.
