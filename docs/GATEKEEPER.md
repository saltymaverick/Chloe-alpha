# Gatekeeper

## Purpose

The Gatekeeper is the "doorman" for automation in Chloe-alpha. It evaluates system health, PF thresholds, and risk constraints to decide whether automation (Reflection→Tuner→ARE→Evolver→Mutations) is allowed to proceed.

## Architecture

### Core Module: `engine_alpha/evolve/gatekeeper.py`

The gatekeeper provides:

- **`load_sanity_report()`**: Loads system sanity report
- **`load_pf_summary()`**: Loads PF summary from reflection_input.json
- **`evaluate_gate_status()`**: Evaluates whether automation is allowed
- **`save_gatekeeper_report()`**: Saves gatekeeper report to JSON

### CLI Tool: `tools/run_gatekeeper_cycle.py`

Runs the complete gatekeeper cycle:
1. Runs system sanity check
2. Evaluates gate status
3. Saves gatekeeper report
4. Prints summary

## Gate Evaluation Logic

The gatekeeper evaluates two main gates:

### 1. Sanity Gate

Checks:
- System sanity report exists and `summary.success == true`
- Shadow mode is enabled
- No critical errors in imports, JSON contracts, or tools

**Result**: `sanity_ok = true` if all checks pass

### 2. PF Gate

Checks:
- PF summary is available
- Tier1 symbols have:
  - Exploration PF ≥ threshold (default: 1.0)
  - Exploration trades ≥ threshold (default: 5)

**Result**: `pf_ok = true` if Tier1 symbols meet thresholds

### Final Decision

Automation is allowed only if:
- `sanity_ok == true` AND
- `pf_ok == true`

## Output Format

### `reports/system/gatekeeper_report.json`

```json
{
  "sanity_ok": true,
  "pf_ok": true,
  "allow_automation": true,
  "reasons": [
    "Sanity suite passed",
    "PF for Tier1 symbols above threshold (1.0) and MinTrades (5) reached for 3 symbols",
    "All gates passed - automation allowed"
  ],
  "thresholds": {
    "min_pf": 1.0,
    "min_trades": 5
  },
  "evaluated_at": "2025-12-04T22:00:00+00:00"
}
```

## Integration with Automation

### Nightly Orchestrator

The nightly orchestrator should:

1. Run gatekeeper cycle: `python3 -m tools.run_gatekeeper_cycle`
2. Load gatekeeper report: `reports/system/gatekeeper_report.json`
3. Check `allow_automation` flag
4. Only proceed with automation if `allow_automation == true`

### Example Integration

```python
from engine_alpha.evolve.gatekeeper import safe_load_json
from pathlib import Path

gatekeeper_report = safe_load_json(Path("reports/system/gatekeeper_report.json"))

if gatekeeper_report.get("allow_automation"):
    # Proceed with automation
    run_reflection_cycle()
    run_tuner_cycle()
    run_evolver_cycle()
else:
    # Block automation
    print("Automation blocked by gatekeeper")
    for reason in gatekeeper_report.get("reasons", []):
        print(f"  - {reason}")
```

## Thresholds

Thresholds can be configured in `config/tuning_rules.yaml`:

```yaml
automation:
  min_pf: 1.0
  min_trades: 5
```

If not specified, defaults are used:
- `min_pf`: 1.0
- `min_trades`: 5

## Advisory-Only Operation

**IMPORTANT**: The Gatekeeper is **read-only** and **advisory-only**:

- ✅ Reads from sanity report and PF summary
- ✅ Produces gate decisions
- ❌ Does NOT modify any configs
- ❌ Does NOT change live trading behavior
- ❌ Does NOT make exchange API calls
- ❌ Does NOT move funds

## Usage

Run the gatekeeper cycle:

```bash
python3 -m tools.run_gatekeeper_cycle
```

This will:
1. Run system sanity check
2. Evaluate gate status
3. Write `reports/system/gatekeeper_report.json`
4. Print summary to stdout

## Dependencies

The Gatekeeper requires:

- `reports/system/sanity_report.json` (from `tools.system_sanity`)
- `reports/gpt/reflection_input.json` (for PF summary)
- `config/tuning_rules.yaml` (for thresholds, optional)

If any of these files are missing, the Gatekeeper will gracefully handle it and report accordingly.

## Future Enhancements

Potential future enhancements:

1. **Time-Based Gates**: Require gates to pass for N consecutive days before allowing automation
2. **Symbol-Specific Gates**: Different thresholds for different symbol tiers
3. **Risk-Based Gates**: Incorporate risk metrics (drawdown, volatility, etc.)
4. **Market Condition Gates**: Block automation during extreme market conditions
5. **Manual Override**: Allow manual override of gate decisions (with audit trail)


