# Nightly Research Guide

## Overview

The nightly research loop allows Chloe to "learn from the big CSV" safely via offline, batched analysis and threshold tuning.

## Architecture

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

## Usage

### Manual Research (Recommended Initially)

```bash
cd /root/Chloe-alpha
source venv/bin/activate
export PYTHONPATH=/root/Chloe-alpha

# Analyze only (no tuning):
python3 -m tools.nightly_research

# Analyze + tune (dry run, review suggestions):
python3 -m tools.nightly_research --tune

# Analyze + tune + apply thresholds:
python3 -m tools.nightly_research --tune --apply

# Full auto: analyze + tune + apply + restart:
python3 -m tools.nightly_research --tune --apply --restart
```

### Automated Nightly Research (After Validation)

```bash
# Copy service files
sudo cp tools/nightly_research.service /etc/systemd/system/
sudo cp tools/nightly_research.timer /etc/systemd/system/

# Enable and start timer
sudo systemctl daemon-reload
sudo systemctl enable nightly_research.timer
sudo systemctl start nightly_research.timer

# Check status
sudo systemctl status nightly_research.timer
sudo systemctl list-timers nightly_research.timer
```

The timer runs daily at 2 AM UTC.

## Workflow

1. **Wait for Data**: Let Chloe accumulate 20-30 meaningful trades
2. **Run Research**: Execute `nightly_research --tune` manually
3. **Review Suggestions**: Check GPT's threshold proposals
4. **Apply (Optional)**: Use `--apply` to update configs
5. **Restart (Optional)**: Use `--restart` to pick up new thresholds

## Why Not Auto-Tune Every Bar?

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

## Files Created

- `tools/nightly_research.py` - Main research script
- `tools/nightly_research.service` - Systemd service unit
- `tools/nightly_research.timer` - Systemd timer unit

## Related Tools

- `tools/signal_return_analyzer.py` - Multi-horizon performance analysis
- `tools/gpt_threshold_tuner.py` - GPT-driven threshold tuning
- `tools/inspect_conf_ret_bins.py` - Inspect confidence/return bins
- `tools/chloe_checkin.py` - Quick status check

