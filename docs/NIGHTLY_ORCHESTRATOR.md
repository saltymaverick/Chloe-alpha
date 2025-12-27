# Nightly Orchestrator

## Overview

The Nightly Orchestrator is the central automation coordinator for Chloe's research and intelligence stack. It runs the full intelligence pipeline only when system health checks pass and gatekeeper allows automation.

## Architecture

### Components

1. **System Sanity Check**: Validates Python imports, JSON contracts, tool executions, and shadow mode enforcement
2. **Gatekeeper**: Evaluates whether automation is safe to proceed based on PF thresholds and risk constraints
3. **Nightly Research Cycle**: Runs all research/intelligence passes in sequence

### Research Steps

The nightly research cycle runs the following steps in order:

1. **ARE** (Aggregated Research Engine): Multi-horizon trade performance analysis
2. **Reflection**: GPT-powered symbol performance analysis and tier assignment
3. **Tuner**: GPT-powered threshold tuning proposals
4. **Dream**: GPT-powered scenario analysis and trade quality review
5. **Quality Scores**: Volatility-adjusted symbol quality metrics
6. **Evolver**: Strategy evolution and promotion/demotion logic
7. **Mutation Preview**: Preview of proposed strategy mutations
8. **Memory Snapshot**: Capture GPT outputs and research data for future cycles
9. **Meta-Review**: Contradiction detection and stability analysis
10. **Capital Overview**: Advisory capital allocation recommendations

## Usage

### Manual Run

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Run full orchestration
python3 -m tools.nightly_orchestrator

# Or run research cycle only (bypasses sanity/gatekeeper)
python3 -m tools.nightly_research_cycle
```

### Automated Scheduling (Example Cron)

```bash
# Run Chloe nightly research at 02:30 UTC
# 30 2 * * * cd /root/Chloe-alpha && source venv/bin/activate && \
#   set -a; source .env; set +a && \
#   export PYTHONPATH=/root/Chloe-alpha && \
#   python3 -m tools.nightly_orchestrator >> logs/nightly_orchestrator.log 2>&1
```

**Note**: The cron entry above is commented out. Do NOT install it automatically. Review and test manually first.

## Output Files

### Orchestration Report

`reports/pipeline/nightly_orchestration.json`:

```json
{
  "ts": "2025-12-05T02:01:00Z",
  "sanity_ok": true,
  "gate_decision": true,
  "research_run": true,
  "reasons": [
    "System sanity passed",
    "Gatekeeper allowed automation",
    "Nightly research cycle executed"
  ]
}
```

### Research Summary

`reports/pipeline/nightly_research_summary.json`:

```json
{
  "ts": "2025-12-05T02:00:00Z",
  "steps": [
    {"name": "ARE", "status": "OK"},
    {"name": "Reflection", "status": "OK"},
    {"name": "Tuner", "status": "OK"},
    ...
  ],
  "notes": [
    "All steps attempted; see logs for details if any failures."
  ]
}
```

## Safety Guarantees

### Advisory-Only

- **No automatic config writes**: All tuning proposals and mutations are preview-only
- **No exchange API calls**: Orchestrator never interacts with exchanges directly
- **Shadow mode enforced**: All exchange operations remain in shadow mode

### Gate Conditions

Research cycle runs ONLY when:

1. **System Sanity**: All Python imports, JSON contracts, and tools pass validation
2. **Gatekeeper**: PF thresholds and risk constraints allow automation

If either gate fails, research cycle is skipped and reasons are logged.

### Error Handling

- Each research step is wrapped in try/except
- One step failure does not crash the entire cycle
- All failures are logged in the summary report
- Orchestrator continues even if individual steps fail

## Integration

### With GPT v3

When GPT flags are enabled:

- `USE_GPT_REFLECTION_V2=true`: Reflection uses v3 prompts
- `USE_GPT_TUNER_V2=true`: Tuner uses v3 prompts
- `USE_GPT_DREAM=true`: Dream uses v3 prompts
- `USE_GPT_*_MEMORY=true`: Cycles load memory context

### With Research Memory

Memory snapshots are taken automatically after research cycles complete, enabling:

- GPT consistency across cycles
- Meta-reasoner contradiction detection
- Historical analysis

### With Meta-Reasoner

Meta-reasoner analyzes recent memory entries to detect:

- Tier instability
- Contradictory tuning proposals
- Reflection-Tuner disagreements

## Future Phases

As of Phase 4, all tuning/mutations are **preview only**. Future phases may introduce:

- Explicit `apply_mutations` step behind stronger gates
- Automated tuning application with rollback capability
- Integration with live trading (with additional safety layers)

## Troubleshooting

### Research Cycle Skipped

If research cycle is skipped, check:

1. **Sanity Report**: `reports/system/sanity_report.json`
   - Look for `summary.success == false`
   - Review `summary.errors` for specific issues

2. **Gatekeeper Report**: `reports/system/gatekeeper_report.json`
   - Check `allow_automation == false`
   - Review `reasons` for denial reasons

### Step Failures

If individual steps fail:

1. Check the step's specific error in `nightly_research_summary.json`
2. Run the step manually to see full traceback:
   ```bash
   python3 -m tools.run_reflection_cycle  # Example
   ```
3. Verify required input files exist (e.g., `reflection_input.json`)

### Missing Tools

If a tool is missing (e.g., `capital_overview`):

- The orchestrator handles missing tools gracefully
- Step status will be "FAIL" with ImportError
- Other steps continue normally

