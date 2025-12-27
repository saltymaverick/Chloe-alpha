# Tuning Self-Evaluation Engine

## Overview

The **Tuning Self-Evaluation Engine** lets Chloe evaluate her own tuning decisions by comparing actual trade performance before vs after each tuning event. This creates a feedback loop where Chloe can learn whether her tuning proposals actually helped, hurt, or were inconclusive.

**Purpose:**
- Learn from tuning decisions over time
- Identify which symbols' tuning is working
- Detect when tuning may need to be halted or reversed
- Build toward stronger Alpha Chloe through self-reflection

**Key Safety:**
- ✅ Advisory-only — no auto-revert, no auto-apply
- ✅ Read-only — does not change configs or trading behavior
- ✅ Honest scoring — classifies outcomes as improved/degraded/inconclusive

## How It Works

### Evaluation Process

For each tuning event in `tuning_reason_log.jsonl`:

1. **Identify tuning event** — timestamp and symbol proposals
2. **Load trade data** — all trades from `trades.jsonl`
3. **Split windows** — before vs after the tuning event timestamp
4. **Compare metrics** — PF, win rate, average P&L
5. **Classify outcome** — improved / degraded / inconclusive

### Classification Rules

**Improved:**
- PF_after > PF_before * 1.1 (at least 10% improvement)
- Or PF improved from finite to infinite (perfect)
- Or maintained perfect PF with better win/loss ratio

**Degraded:**
- PF_after < PF_before * 0.9 (at least 10% degradation)
- Or PF degraded from infinite to finite
- Or maintained perfect PF but win/loss ratio worsened

**Inconclusive:**
- PF changed by less than 10%
- Insufficient sample size (< 5 trades in before/after windows)
- PF calculation errors

### Window Size

Default window size is **5 trades** (configurable). This means:
- Last 5 trades before tuning event
- First 5 trades after tuning event

This provides a reasonable sample while being responsive to recent changes.

## Output Format

**File:** `reports/research/tuning_self_eval.json`

```json
{
  "generated_at": "2025-12-05T21:30:00+00:00",
  "window_size": 5,
  "events": [
    {
      "ts": "2025-12-05T20:15:00+00:00",
      "symbols": {
        "ETHUSDT": {
          "status": "improved",
          "detail": "PF improved from 2.50 to 3.20 (ratio: 1.28)",
          "before": {
            "pf": 2.5,
            "avg": 0.15,
            "win_rate": 0.6,
            "wins": 3,
            "losses": 2,
            "count": 5
          },
          "after": {
            "pf": 3.2,
            "avg": 0.18,
            "win_rate": 0.6,
            "wins": 3,
            "losses": 2,
            "count": 5
          }
        },
        "ADAUSDT": {
          "status": "degraded",
          "detail": "PF degraded from 1.20 to 0.85 (ratio: 0.71)",
          "before": {
            "pf": 1.2,
            "avg": -0.05,
            "win_rate": 0.4,
            "wins": 2,
            "losses": 3,
            "count": 5
          },
          "after": {
            "pf": 0.85,
            "avg": -0.08,
            "win_rate": 0.4,
            "wins": 2,
            "losses": 3,
            "count": 5
          }
        }
      }
    }
  ],
  "summary": {
    "ETHUSDT": {
      "improved": 3,
      "degraded": 0,
      "inconclusive": 1
    },
    "ADAUSDT": {
      "improved": 0,
      "degraded": 2,
      "inconclusive": 2
    }
  }
}
```

## Usage

### Run Self-Evaluation

```bash
python3 -m tools.run_tuning_self_eval
```

### View Results

```bash
# View full results
cat reports/research/tuning_self_eval.json | python3 -m json.tool

# View summary only
cat reports/research/tuning_self_eval.json | python3 -m json.tool | grep -A 10 '"summary"'
```

### View in Intel Dashboard

The intel dashboard automatically shows the tuning self-eval summary:

```bash
python3 -m tools.intel_dashboard
```

Look for the "TUNING SELF-EVAL SUMMARY" section.

## Integration

### Nightly Research Cycle

The self-evaluation is integrated into the nightly research cycle:

```python
("TuningSelfEval", "tools.run_tuning_self_eval", "main"),
```

This runs automatically after each nightly research cycle, evaluating all tuning events.

### Intel Dashboard

The dashboard shows a summary table:

```
TUNING SELF-EVAL SUMMARY
----------------------------------------------------------------------
Symbol   improved  degraded  inconclusive
---------------------------------------------------
ADAUSDT         0         2             2
ETHUSDT         3         0             1
```

## Interpretation

### What to Look For

**Strong Positive Signals:**
- Multiple "improved" outcomes for a symbol
- Consistent improvement across tuning events
- High improved/degraded ratio

**Warning Signals:**
- Multiple "degraded" outcomes for a symbol
- Consistent degradation across tuning events
- Low improved/degraded ratio

**Neutral:**
- Mostly "inconclusive" outcomes
- Early in tuning history (not enough data yet)
- Small sample sizes

### Example Interpretations

**ETHUSDT: improved=3, degraded=0, inconclusive=1**
- ✅ Tuning appears to be working well
- ✅ Consider continuing or even increasing tuning frequency
- ✅ Chloe's proposals for ETHUSDT are effective

**ADAUSDT: improved=0, degraded=2, inconclusive=2**
- ⚠️ Tuning may be hurting performance
- ⚠️ Consider halting tuning for this symbol
- ⚠️ May need to reverse recent tuning changes manually

**SOLUSDT: improved=0, degraded=0, inconclusive=4**
- ℹ️ Not enough data yet to evaluate
- ℹ️ Need more trades or tuning events
- ℹ️ Continue monitoring

## Caveats

### Sample Size Requirements

- Needs at least 5 trades before and after each tuning event
- Early tuning events may show mostly "inconclusive" results
- More tuning events = more reliable evaluation

### Time Windows

- Uses fixed window size (default 5 trades)
- Does not account for market regime changes
- May miss longer-term effects

### Trade Filtering

- Only analyzes "close" events (completed trades)
- Filters by symbol automatically
- Does not distinguish exploration vs normal lane trades

### PF Calculation

- Uses standard PF formula: sum(wins) / abs(sum(losses))
- Infinite PF when no losses (perfect performance)
- May be sensitive to outliers

## Future Enhancements

Potential improvements:

1. **Regime-Aware Evaluation** — Account for market regime changes
2. **Longer Windows** — Track longer-term effects (10-20 trades)
3. **Exploration vs Normal** — Separate evaluation for each lane
4. **Auto-Revert Suggestions** — Recommend reversing degraded tuning
5. **Tuning Effectiveness Score** — Aggregate score per symbol
6. **Tuner v5 Training** — Use evaluation results to improve tuner

## Troubleshooting

### No Results

**Possible reasons:**
- No tuning events in `tuning_reason_log.jsonl`
- No trades in `trades.jsonl`
- Insufficient trades before/after tuning events

**Check:**
```bash
# Verify tuning events exist
wc -l reports/gpt/tuning_reason_log.jsonl

# Verify trades exist
wc -l reports/trades.jsonl

# Check latest tuning event
tail -n 1 reports/gpt/tuning_reason_log.jsonl | python3 -m json.tool
```

### All Inconclusive

**Possible reasons:**
- Not enough trades yet
- Tuning events too recent (not enough after-trades)
- Window size too large for available data

**Solution:**
- Wait for more trades to accumulate
- Reduce window size (modify code or add CLI flag)
- Check that trades are being logged correctly

## Safety

⚠️ **This module is read-only and advisory-only.**

⚠️ **It does NOT:**
- Auto-revert tuning changes
- Modify configs
- Change trading behavior
- Apply or remove overrides

⚠️ **It only:**
- Analyzes historical data
- Provides evaluation scores
- Suggests what happened (not what to do)

All decisions about tuning remain manual and human-controlled.

