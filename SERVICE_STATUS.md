# Chloe Service Status

## Current Configuration

**Service:** `chloe.service`  
**Status:** ✅ Active and running  
**Script:** `tools/run_paper_loop.py`  
**Timeframe:** 15m  
**Mode:** PAPER (not DRY_RUN)

## Service Details

- **Working Directory:** `/root/Chloe-alpha`
- **Executable:** `/usr/bin/python3 tools/run_paper_loop.py`
- **Restart Policy:** Always (restarts after 5 seconds on crash)
- **Logs:** 
  - `/root/Chloe-alpha/logs/chloe.service.log`
  - `/root/Chloe-alpha/logs/chloe.service.error.log`

## What It Does

1. **Continuously monitors** for new 15m bars
2. **Calls `run_step_live()`** when a new bar is detected
3. **Processes decisions** (regime, confidence, entry/exit)
4. **Logs trades** to `reports/trades.jsonl` when conditions are met
5. **Updates PF reports** automatically

## Current Behavior

The service is **running correctly** and processing bars. You may see:

- **REGIME-GATE messages:** Normal - CHOP regime blocks entries (only trend_down/high_vol allowed)
- **ENTRY-THRESHOLD messages:** Normal - Confidence below threshold
- **No trades:** Expected if regime is CHOP or confidence is too low

## Monitoring Commands

### Check Service Status
```bash
sudo systemctl status chloe.service
```

### View Live Logs
```bash
sudo journalctl -u chloe.service -f
```

### Check Trade Count
```bash
wc -l reports/trades.jsonl
tail -5 reports/trades.jsonl | jq .
```

### Quick Status
```bash
./tools/check_status.sh
python tools/monitor_status.py
```

## Expected Trade Behavior

**Trades will occur when:**
- ✅ Regime is `trend_down` or `high_vol` (CHOP blocks entries)
- ✅ Confidence ≥ `entry_min_confidence` (currently 0.40)
- ✅ Drift score < `max_drift_for_entries` (currently 0.60)
- ✅ No existing position in same direction

**Current state:**
- Regime: CHOP (blocks entries)
- Confidence: ~0.40 (meets threshold)
- Drift: ~0.44 (below threshold)
- **Result:** No new entries until regime changes to trend_down or high_vol

## Troubleshooting

### Service Not Running
```bash
sudo systemctl restart chloe.service
sudo systemctl status chloe.service
```

### No Trades Appearing
- Check regime: `python tools/monitor_status.py` (should show regime)
- Check confidence: Should be ≥ 0.40
- Check logs: `tail -50 logs/chloe.service.log`

### Service Keeps Restarting
- Check error log: `tail -50 logs/chloe.service.error.log`
- Verify script is executable: `ls -la tools/run_paper_loop.py`
- Check Python dependencies

## Next Steps

1. ✅ Service is running and processing bars
2. ⏳ Wait for regime to change to `trend_down` or `high_vol` for entries
3. ⏳ Monitor trade count - should increase when conditions are met
4. ⏳ After 50-100 trades, run GPT tuner: `python tools/run_threshold_tuner.py`

