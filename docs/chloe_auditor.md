# Chloe Auditor - AI Risk Officer

## Overview

`tools/chloe_auditor.py` is a comprehensive health check tool that answers:

**"Is Chloe currently healthy, consistent, and ready to trade with maximum profit-seeking intelligence?"**

## Usage

```bash
# Check live/PAPER state only
python3 -m tools.chloe_auditor live

# Run canonical window backtests
python3 -m tools.chloe_auditor backtest

# Full health check (live + backtest + analysis)
python3 -m tools.chloe_auditor full
```

## Exit Codes

- **0** = ✅ Good to trade
- **1** = ⚠️ Trade with caution / monitor
- **2** = ❌ Stop and inspect before trading

## What It Checks

### Live Health (`live` subcommand)

Checks current live/PAPER trading state:

- **PF Overall**: Profit factor from meaningful trades (TP/SL, |pct| >= 0.0005)
- **Meaningful Closes**: Count of non-scratch trades
- **Scratch Ratio**: Percentage of trades that are scratch (too small to matter)
- **PF by Regime**: Performance in trend_down, high_vol, chop, trend_up
- **Core Status**: REC, risk band, multiplier, drawdown

**Health Thresholds:**
- Minimum meaningful closes: 20
- Minimum PF: 1.1
- Maximum scratch ratio: 0.7
- Regime PF: trend_down/high_vol should have PF >= 0.9 (if >10 closes)

### Backtest Health (`backtest` subcommand)

Runs canonical window backtests and analyzes results:

**Canonical Windows:**
1. **trend_down_mvp**: 2022-04-01 to 2022-06-30 (dump period)
2. **high_vol_mvp**: 2021-01-01 to 2021-03-31 (volatile period)
3. **chop_sanity**: 2021-09-01 to 2021-10-15 (sideways market)

For each window:
- Runs backtest using `tools.backtest_harness`
- Analyzes results using `tools.backtest_report` and `tools.pf_doctor_filtered`
- Checks:
  - Meaningful closes >= 10
  - PF >= 1.1 (warn if 0.9-1.1, fail if <0.9)
  - Equity ratio >= 0.9 (no excessive bleed)
  - Special handling for `chop_sanity` (entries gated off, so low PF is OK)

### Full Health (`full` subcommand)

Runs both live and backtest checks, plus:

- Optional signal analysis summary (if `reports/analysis/conf_ret_summary.json` exists)
- Shows best confidence ranges per regime
- Aggregates all issues and recommendations
- Returns combined exit code

## Output Format

```
================================================================================
[ LIVE HEALTH ]
================================================================================

  Status: ✅ OK
  PF: 1.32 (35 meaningful closes)
  Scratch ratio: 0.42 (OK)
  REC: REVIEW | Band: A | Mult: 1.0
  Trades: 12 opens, 35 closes

  Regime PF:
    trend_down  : PF=17.77 (closes=5) strong
    high_vol    : PF=1.73 (closes=17) good
    chop        : PF=0.35 (closes=12) weak (gated off)
    trend_up    : PF=0.00 (closes=1) (gated off)

  Issues: none
```

## Integration

The auditor can be integrated into:

- **CI/CD pipelines**: Fail builds if exit code != 0
- **Cron jobs**: Daily health checks
- **Pre-trade checks**: Run before enabling live trading
- **Monitoring**: Alert if status degrades

Example cron job:
```bash
# Daily health check at 6 AM UTC
0 6 * * * cd /root/Chloe-alpha && export PYTHONPATH=/root/Chloe-alpha && python3 -m tools.chloe_auditor full >> /var/log/chloe_auditor.log 2>&1
```

## Configuration

Health thresholds are defined at the top of `tools/chloe_auditor.py`:

```python
LIVE_MIN_MEANINGFUL_CLOSES = 20
LIVE_MIN_PF = 1.1
LIVE_MAX_SCRATCH_RATIO = 0.7
BACKTEST_MIN_MEANINGFUL_CLOSES = 10
BACKTEST_MIN_PF = 1.1
BACKTEST_WARN_PF = 0.9
BACKTEST_MIN_EQUITY_RATIO = 0.9
```

Canonical windows are defined in `CANONICAL_WINDOWS` list (easy to edit).

## Safety

- ✅ Read-only tool (never modifies thresholds or trading behavior)
- ✅ Uses existing tools programmatically (no code duplication)
- ✅ No lab/backtest hacks (uses unified logic)
- ✅ Clear exit codes for automation

## Example Workflow

```bash
# 1. Check if Chloe is ready to trade
python3 -m tools.chloe_auditor full
if [ $? -eq 0 ]; then
    echo "✅ Chloe is healthy - ready to trade"
else
    echo "⚠️  Issues detected - review before trading"
fi

# 2. Run backtest health check
python3 -m tools.chloe_auditor backtest

# 3. Check live state only
python3 -m tools.chloe_auditor live
```


