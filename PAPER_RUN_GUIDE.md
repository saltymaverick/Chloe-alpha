# Paper Run Guide - Chloe Alpha

## Overview

This guide covers running Chloe in paper mode, collecting trades, and using the GPT threshold tuner to refine her behavior.

---

## 1. Final Threshold Configuration

**Current thresholds** (in `config/risk.yaml`):
- `entry_min_confidence`: 0.40 (allows entries at ~0.402 confidence)
- `exit_min_confidence`: 0.30
- `max_drift_for_entries`: 0.60
- `max_drift_for_open_positions`: 0.70

**Confidence engine settings**:
- `DRIFT_PENALTY_ALPHA`: 0.5 (softened from 1.0)

---

## 2. Running Paper Mode

### Prerequisites
- ✅ Dry-run mode verified (PF protection working)
- ✅ Thresholds softened and loaded from config
- ✅ Full quant stack wired (signals → regime → drift → confidence → sizing → entry/exit)

### Starting Paper Run

**Option A: Using autonomous_trader directly**
```bash
# Ensure NOT in dry-run mode
unset MODE
unset CHLOE_DRY_RUN

# Run paper mode (default)
python -m engine_alpha.loop.autonomous_trader
```

**Option B: Using existing runner script**
```bash
# Use whatever script you've historically used for paper trading
# Just ensure MODE is not set to DRY_RUN
python tools/your_paper_runner.py
```

**Option C: Live data mode (if available)**
```bash
python -m engine_alpha.loop.autonomous_trader --live
# or
MODE=PAPER python -m engine_alpha.loop.autonomous_trader
```

### What Happens Per Tick

In paper mode, Chloe will:
1. ✅ Build SignalContext
2. ✅ Compute Flow / Vol / Micro / Cross signals
3. ✅ Compute RegimeState
4. ✅ Compute DriftState from actual paper trades
5. ✅ Compute ConfidenceState (with softened drift penalty)
6. ✅ Compute size_multiplier from confidence + vol + drift
7. ✅ Call `should_enter_trade` / `should_exit_trade`
8. ✅ Log real paper trades to `reports/trades.jsonl`
9. ✅ Update PF reports (`reports/pf_local.json`, `reports/pf_live.json`)

### Monitoring Progress

**Quick status check:**
```bash
./tools/check_status.sh
```

Shows timeframe, phase, trades, PF, and ETHUSDT status at a glance.

**Richer status view:**
```bash
python tools/monitor_status.py
```

Shows detailed per-asset status, latest regime/drift/confidence for ETH, and recent trades.

**Detailed overseer report:**
```bash
python -m tools.overseer_report
```

Shows comprehensive per-asset breakdown with PF, trades, and promotion candidates.

**Check trade count:**
```bash
wc -l reports/trades.jsonl
```

**Check PF:**
```bash
cat reports/pf_local.json
```

**Check recent decisions:**
```bash
tail -20 reports/trades.jsonl | jq .
```

### Target: 50-100 Trades

Let the paper run accumulate at least 50-100 trades before running the GPT tuner. This gives enough data for meaningful analysis.

---

## 3. Using GPT Threshold Tuner

### After 50-100 Trades

Run the tuner:
```bash
python tools/run_threshold_tuner.py
```

### What the Tuner Does

1. **Loads recent trades** (default: last 150, requires ≥50)
2. **Computes stats**:
   - `pf_local`
   - `pf_by_regime`
   - `pf_by_confidence_band`
   - `drift_state` (pf_local, drift_score, confidence_return_corr)
3. **Reads current thresholds** from `config/risk.yaml`
4. **Calls GPT** with structured prompt
5. **Gets JSON suggestion** for:
   - `entry_min_confidence`
   - `exit_min_confidence`
   - `max_drift_for_entries`
   - `max_drift_for_open_positions`
6. **Clamps changes** by `max_change_per_step` (safety limits)
7. **Saves proposal** to `reports/tuning_proposals.jsonl`
8. **Prints proposal** to terminal

### Example Output

```
=== GPT Threshold Proposal ===
Timestamp: 2025-11-27T23:45:00Z
Current thresholds:
  entry_min_confidence: 0.40
  exit_min_confidence: 0.30
  max_drift_for_entries: 0.60
  max_drift_for_open_positions: 0.70

Suggested thresholds:
  entry_min_confidence: 0.47 (+0.07)
  exit_min_confidence: 0.28 (-0.02)
  max_drift_for_entries: 0.55 (-0.05)
  max_drift_for_open_positions: 0.70 (no change)

Rationale:
  PF_local is 1.12, showing positive edge. High-confidence bands (0.6-1.0) 
  have PF 1.25, while low-confidence (0.3-0.6) have PF 0.95. Slightly 
  raising entry_min_confidence to filter lower-quality trades while 
  keeping exit threshold flexible.

Stats summary:
  Trade count: 87
  PF_local: 1.12
  Drift score: 0.23
```

---

## 4. Evaluating GPT Proposals

### Sanity Checks

**1. Is PF_local at least not horrible?**
- ✅ PF_local ~1.0-1.1 or higher → tuning is refinement
- ⚠️ PF_local ~0.6-0.9 → treat suggestions cautiously (triage mode)
- ❌ PF_local < 0.6 → fix underlying issues before tuning thresholds

**2. Are high-confidence bands doing better than low ones?**
- ✅ High-confidence (0.6-1.0) PF > Low-confidence (0.3-0.6) PF → Good calibration
- ⚠️ High-confidence PF < Low-confidence PF → Confidence may be miscalibrated
- GPT should suggest tightening entry thresholds if high-confidence trades are losing

**3. Are suggested changes modest?**
- ✅ Small moves: 0.40 → 0.47, 0.30 → 0.28 (within `max_change_per_step`)
- ❌ Large jumps: 0.40 → 0.90 (shouldn't happen due to clamping, but be suspicious)

**4. Does rationale make sense?**
- ✅ "Chop regimes losing; raise entry_min_confidence" → Makes sense
- ✅ "High-confidence bands performing well; slight tightening" → Makes sense
- ❌ Rationale ignores your stats or contradicts the data → Reject

### Decision Process

**If proposal passes sniff test:**
1. Manually edit `config/risk.yaml` to apply new values
2. Rerun paper loop with updated config
3. Let more trades accumulate
4. Run tuner again later (iterative refinement)

**If proposal doesn't feel right:**
1. Ignore that proposal (it's logged in `reports/tuning_proposals.jsonl` for history)
2. Let more data accumulate
3. Try tuner again later

---

## 5. Current System Status

✅ **Full quant brain**: Signals → Regime → Drift → Confidence → Sizing → Entry/Exit  
✅ **Dry-run mode**: Test logic without touching PF  
✅ **PF protection**: Dry-run never modifies real PF files  
✅ **Paper mode**: Collect real behavior over time  
✅ **GPT threshold advisor**: Proposes, never auto-applies  
✅ **Thresholds softened**: Entry at 0.40, drift penalty reduced  

**Next steps:**
1. Run paper mode until 50-100 trades accumulate
2. Run GPT tuner: `python tools/run_threshold_tuner.py`
3. Evaluate proposal and decide whether to accept
4. Iterate

---

## Files Reference

- **Config**: `config/risk.yaml` (thresholds, tuning settings)
- **Trades**: `reports/trades.jsonl` (all paper trades)
- **PF Reports**: `reports/pf_local.json`, `reports/pf_live.json`
- **Tuner Proposals**: `reports/tuning_proposals.jsonl`
- **Dry-run logs**: `reports/dry_run_decisions.jsonl`, `reports/dry_run_trades.jsonl`

---

## Troubleshooting

**No entries after threshold tweak:**
- Check confidence values in dry-run decisions
- Verify thresholds are loaded from config (not hardcoded)
- Consider lowering entry_min_confidence further (but be cautious)

**PF files modified during dry-run:**
- Verify `MODE=DRY_RUN` is set
- Check `update_pf_reports()` has dry-run guard

**GPT tuner returns None:**
- Need at least 50 trades (check `min_trades_for_tuning` in config)
- Verify GPT client is configured (API key set)

**Confidence not varying:**
- May be due to static input data in dry-run
- Paper mode with real data should show variation
- Check signal computation is using different candles per tick

