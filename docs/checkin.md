# Chloe Check-in Tool

The `chloe_checkin` tool provides a unified, human-friendly summary of Chloe's trading status and performance.

## Usage

### Basic Check-in

```bash
cd /root/Chloe-alpha
export PYTHONPATH=/root/Chloe-alpha
python3 -m tools.chloe_checkin
```

This prints:
- **Core Status**: REC, risk band, opens/closes count
- **PF Summary**: All closes (scratch excluded), meaningful closes, PF
- **Filtered PF**: TP/SL trades only, |pct| >= 0.0005, broken down by regime
- **Last 5 Meaningful Trades**: Recent trades with full metadata

### With GPT Reflection

```bash
python3 -m tools.chloe_checkin --reflect
```

This adds a GPT reflection section that analyzes the filtered PF data and provides insights.

**Requirements for `--reflect`:**
- `OPENAI_API_KEY` environment variable set
- `openai` Python library installed
- Valid API key with access to GPT-4o

If these are not available, the tool will skip reflection gracefully and show a note.

## Understanding the Output

### PF Summary (All Closes)

This shows PF calculated over all closes, excluding scratch trades (`is_scratch=True`).

- **Scratch closes**: Trades with `|pct| < 0.0005` and `exit_reason` in `{"sl", "drop", "decay"}`
- **Meaningful closes**: All other closes
- **PF**: Profit Factor = (sum of positive pct) / (sum of absolute negative pct)

### Filtered PF

This shows PF calculated only over "meaningful" trades:
- `|pct| >= 0.0005` (0.05% minimum move)
- `exit_reason` in `{"tp", "sl"}` (only take profit and stop loss)
- Excludes scratch trades

**Why filtered PF matters:**
- Raw PF can be diluted by noise trades (micro-moves, signal drops, etc.)
- Filtered PF shows Chloe's actual edge on trades with meaningful price movement
- PF by regime shows where Chloe is strong (trend_down, high_vol) vs weak (chop, trend_up)

### Last 5 Meaningful Trades

Shows the most recent trades that meet the filtered PF criteria, with:
- Timestamp
- Pct (signed percentage return)
- Exit reason + label
- Regime (trend_down, high_vol, chop, trend_up)
- Risk band and multiplier

## What This Tool Does NOT Do

- **Does not modify trading behavior**: This is a read-only diagnostic tool
- **Does not change thresholds or exits**: All trading logic remains unchanged
- **Does not affect backtests**: Backtest behavior is completely separate

## Integration with Other Tools

The check-in tool reuses logic from:
- `tools.status` - Core status information
- `tools.pf_doctor` - PF summary calculation
- `tools.pf_doctor_filtered` - Filtered PF and regime breakdown
- `tools.run_reflection_gpt` - GPT reflection (when `--reflect` is used)

You can still use these tools individually if you need more detailed output.

## Example Output

```
======================================================================
Chloe Check-in — 2025-11-22T06:10:00Z (MODE=PAPER)
======================================================================

[CORE STATUS]
  REC=REVIEW opens=True pa=False | Risk band=C mult=0.5 dd=0.9999
  Trades (open/close): 12 / 8

[PF SUMMARY — ALL CLOSES]
  Scratch closes (excluded): 3
  Meaningful closes:         5
  Positive pct sum:          +0.234567
  Negative pct sum:          -0.123456
  PF (meaningful only):      1.900000

[FILTERED PF — TP/SL, |pct| >= 0.0005]
  Overall: count=5 wins=3 losses=2 PF=1.350
  By regime:
    trend_down: closes= 2 wins= 2 losses= 0 PF=17.77
    high_vol  : closes= 3 wins= 1 losses= 2 PF= 1.73

[LAST 5 MEANINGFUL TRADES]
  2025-11-22T05:17:21Z  pct=+0.469100  exit=sl(stop_loss)  regime=high_vol  band=C mult=0.5
  2025-11-22T04:15:10Z  pct=-0.123400  exit=sl(stop_loss)  regime=high_vol  band=C mult=0.5
  ...

======================================================================
```


