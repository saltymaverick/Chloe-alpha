# Chloe Learning Architecture

## Overview

Chloe learns from historical CSV data and her own trade history via **offline, batched research** - not live self-tuning. This ensures stability and safety.

## Architecture: Offline Batched Learning

### Live Loop (Fixed Parameters)
- Uses `config/entry_thresholds.json` and `config/regime_enable.json`
- Exit logic: min-hold + price-move + scratch detection
- **No parameter changes during runtime** (stability & safety)

### Research Loop (Offline, Batched)
- Analyzes full CSV via `signal_return_analyzer`
- Multi-horizon performance by regime × confidence
- GPT proposes threshold adjustments
- Updates config files (when `--apply`)
- Restarts service (when `--restart`)

## Why Not Live Self-Tuning?

### Stability & Safety
- Fixed thresholds prevent wild swings
- Auditability: clear parameter history
- No mid-run parameter changes

### Cost & Latency
- GPT calls are expensive at high frequency
- Bulk analysis is more efficient
- Offline tuning doesn't block live loop

### Pattern: Batched Research + Threshold Updates
1. Live loop uses fixed parameters (current "era")
2. Research loop runs nightly/manually (analyzer + GPT tuner)
3. New thresholds promoted via service restart

## Learning Pipeline

### Step 1: Multi-Horizon Analysis
```bash
python3 -m tools.signal_return_analyzer \
  --symbol ETHUSDT \
  --timeframe 1h \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --horizons 1 2 4 8 \
  --output reports/eth_1h_multi_horizon.json
```

This computes PF and stats by:
- Regime (trend_down, high_vol, chop, trend_up)
- Confidence bin (0.55-0.60, 0.60-0.65, etc.)
- Horizon (1-bar, 2-bar, 4-bar, 8-bar forward returns)

### Step 2: GPT Threshold Tuning
```bash
python3 -m tools.gpt_threshold_tuner \
  --summary reports/eth_1h_multi_horizon.json \
  --apply
```

GPT analyzes the multi-horizon stats and proposes:
- Per-regime entry thresholds
- TP/SL confidence thresholds
- Risk band adjustments

### Step 3: Apply & Restart
```bash
sudo systemctl restart chloe.service
```

New thresholds take effect on next service restart.

## Automated Nightly Research

Once validated, enable automated nightly research:

```bash
sudo cp tools/nightly_research.service /etc/systemd/system/
sudo cp tools/nightly_research.timer /etc/systemd/system/
sudo systemctl enable nightly_research.timer
sudo systemctl start nightly_research.timer
```

Runs daily at 2 AM UTC.

## Data Format: Fractional Returns

All `pct` values are stored as **fractional returns**:
- `0.0993` = +9.93%
- `0.0005` = +0.05% (5 bps)
- `-0.001` = -0.1%

This matches:
- CSV analysis format
- Signal return analyzer output
- Scratch threshold: `SCRATCH_THRESHOLD = 0.0005` (0.05% = 5 bps)

## Scratch Detection

Trades are marked as scratches (`is_scratch = true`) when:
- `abs(pct) < 1e-6` (effectively zero)
- `abs(pct) < SCRATCH_THRESHOLD` (0.0005) AND `exit_reason` in `{"tp", "sl", "drop", "decay"}`

Scratches are excluded from PF calculations by default.

## Workflow

1. **Trade**: Chloe accumulates trades under current thresholds
2. **Analyze**: Run multi-horizon analyzer on full CSV
3. **Tune**: GPT proposes threshold adjustments
4. **Apply**: Update configs and restart service
5. **Repeat**: Cycle continues with new thresholds

This is "Chloe learning from the big CSV" - done safely offline.

