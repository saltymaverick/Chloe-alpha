# Systemd Setup - Chloe 15m Paper Loop

## Service Configuration

**File:** `/etc/systemd/system/chloe.service`

**Status:** ✅ Configured and running

**Executes:** `python3 tools/run_paper_loop.py`

**Mode:** PAPER (not DRY_RUN)

## Service Management

### Check Status
```bash
sudo systemctl status chloe.service
```

### View Logs
```bash
# Real-time logs
sudo journalctl -u chloe.service -f

# Or from log files
tail -f /root/Chloe-alpha/logs/chloe.service.log
tail -f /root/Chloe-alpha/logs/chloe.service.error.log
```

### Restart Service
```bash
sudo systemctl restart chloe.service
```

### Stop Service
```bash
sudo systemctl stop chloe.service
```

### Disable Service (prevent auto-start on boot)
```bash
sudo systemctl disable chloe.service
```

## What the Service Does

1. **Detects new 15m bars** automatically
2. **Calls `run_step_live()`** for each new bar
3. **Logs trades** to `reports/trades.jsonl`
4. **Updates PF reports** (`reports/pf_local.json`, `reports/pf_live.json`)
5. **Restarts automatically** if it crashes (RestartSec=5)

## Monitoring

### Quick Status Check
```bash
./tools/check_status.sh
```

### Detailed Status
```bash
python tools/monitor_status.py
```

### Overseer Report
```bash
python -m tools.overseer_report
```

### Recent Trades
```bash
tail -10 reports/trades.jsonl | jq .
```

## Expected Behavior

- **Service runs 24/7** in background
- **Processes new 15m bars** as they arrive
- **Takes trades** when conditions are met (regime gate, confidence threshold, etc.)
- **Logs all activity** to `logs/chloe.service.log`
- **Auto-restarts** on crash (within 5 seconds)

## Troubleshooting

### Service Not Starting
```bash
# Check status
sudo systemctl status chloe.service

# Check error log
tail -50 /root/Chloe-alpha/logs/chloe.service.error.log

# Check if script is executable
ls -la /root/Chloe-alpha/tools/run_paper_loop.py
```

### No Trades Appearing
- Check regime gate: CHOP regime blocks entries (only trend_down/high_vol allowed)
- Check confidence: Must meet `entry_min_confidence` threshold
- Check logs for "REGIME-GATE" or "ENTRY-THRESHOLD" messages

### Service Keeps Restarting
- Check error log for exceptions
- Verify Python dependencies are installed
- Check disk space and file permissions

## Integration with Other Services

- **Nightly research:** Runs separately via `chloe-nightly-research.timer`
- **SWARM:** Runs separately via scheduled jobs
- **Overseer:** Generates reports from trade data

All services work together:
- Chloe trades → logs to `trades.jsonl`
- Nightly research → analyzes trades → updates overseer reports
- Overseer → provides governance layer

