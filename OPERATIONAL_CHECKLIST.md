# Chloe Alpha - Operational Checklist

## ✅ Current Status

**Architecture:** Complete
- Full quant brain (signals → regime → drift → confidence → sizing → entry/exit)
- Dry-run mode with PF protection
- GPT threshold tuner (proposes, doesn't auto-apply)
- Paper mode ready

**Thresholds:**
- `entry_min_confidence`: 0.40
- `exit_min_confidence`: 0.30
- `max_drift_for_entries`: 0.60
- `DRIFT_PENALTY_ALPHA`: 0.5

---

## 📋 Step-by-Step: First Paper Run

### Step 1: Start Paper Run

```bash
# Ensure dry-run is OFF
unset MODE
unset CHLOE_DRY_RUN

# Start Chloe in paper mode
python -m engine_alpha.loop.autonomous_trader

# Or use your existing paper runner script
# python tools/your_paper_runner.py
```

**Goal:** Let trades accumulate. Do nothing else for a bit.

---

### Step 2: Monitor Progress (Occasional Checks)

**Check trade count:**
```bash
wc -l reports/trades.jsonl
```

**Check PF:**
```bash
cat reports/pf_local.json
```

**Check recent trades:**
```bash
tail -n 10 reports/trades.jsonl | jq .
```

**What to look for:**
- Direction (long/short)
- Confidence at entry
- Regime at entry
- Decision reasons

**Target:** 50-100 trades before tuning

---

### Step 3: Run GPT Tuner (After 50-100 Trades)

```bash
python tools/run_threshold_tuner.py
```

**What to review:**
- `trade_count` (should be ≥50)
- `pf_local` (target: ≥1.0 for refinement, ≥0.9 for triage)
- `suggested thresholds` (should be modest changes)
- `rationale` (should make sense with your stats)

**Output location:** `reports/tuning_proposals.jsonl`

---

### Step 4: Evaluate & Decide

**If proposal looks good:**
- PF_local ≥ 1.0
- Changes are modest (within `max_change_per_step`)
- Rationale aligns with stats
- High-confidence bands outperform low-confidence

→ **Accept:** Manually edit `config/risk.yaml` with new thresholds
→ Restart paper run and repeat cycle

**If proposal doesn't feel right:**
- PF_local < 0.9
- Changes seem too aggressive
- Rationale contradicts data

→ **Reject:** Ignore proposal (logged for history)
→ Let more data accumulate, try again later

---

## 🔍 Monitoring

### Quick Status Check

**One-glance snapshot:**
```bash
./tools/check_status.sh
```

Shows:
- Timeframe and phase
- Total trades (all assets)
- PF_local summary
- ETHUSDT specific: trades, PF, status
- Recent entries
- Mode (PAPER/DRY_RUN)

**Richer status view:**
```bash
python tools/monitor_status.py
```

Shows:
- Timeframe and phase
- Per-asset summary (trades, PF, mode)
- For ETHUSDT:
  - Latest regime, drift, confidence state
  - Last 3 trades with details
- Other assets status

**Detailed overseer breakdown:**
```bash
python -m tools.overseer_report
```

Shows:
- Phase and global status
- Per-asset: tier, trading enabled, trades, PF, comments
- Promotion candidates (paper/live)

**Recent trades:**
```bash
tail -5 reports/trades.jsonl | jq .
```

Shows:
- Direction (long/short)
- Size multiplier
- Entry confidence
- PnL/return
- Regime at entry

### Quick Monitoring Commands

**One-liner status check:**
```bash
echo "Trades: $(wc -l < reports/trades.jsonl)" && \
echo "PF_local: $(jq -r '.pf' reports/pf_local.json)" && \
echo "Last trade: $(tail -1 reports/trades.jsonl | jq -r '.ts // .timestamp')"
```

**Check if ready for tuning:**
```bash
TRADE_COUNT=$(wc -l < reports/trades.jsonl)
if [ "$TRADE_COUNT" -ge 50 ]; then
    echo "✅ Ready for GPT tuner ($TRADE_COUNT trades)"
else
    echo "⏳ Need more trades ($TRADE_COUNT/50)"
fi
```

**View recent entry decisions:**
```bash
tail -20 reports/trades.jsonl | jq -r 'select(.type=="open") | "\(.ts) | \(.direction) | conf=\(.confidence) | regime=\(.regime)"'
```

---

## 🚨 When to Come Back for Interpretation

Bring these when you want help interpreting behavior:

1. **PF snapshot:**
   ```bash
   cat reports/pf_local.json
   ```

2. **GPT tuner proposal:**
   ```bash
   tail -1 reports/tuning_proposals.jsonl | jq .
   ```

3. **Sample trades (2-3 examples):**
   ```bash
   tail -5 reports/trades.jsonl | jq .
   ```

**Questions to ask:**
- "Is this Chloe being cautious, or Chloe being broken?"
- "Should I accept this GPT proposal?"
- "Why is she trading like this?"

---

## 📊 Key Files Reference

- **Config:** `config/risk.yaml` (thresholds, tuning settings)
- **Trades:** `reports/trades.jsonl` (all paper trades)
- **PF Reports:** `reports/pf_local.json`, `reports/pf_live.json`
- **Tuner Proposals:** `reports/tuning_proposals.jsonl`
- **Dry-run logs:** `reports/dry_run_*.jsonl` (for testing)

---

## 🎯 Success Criteria

**Good signs:**
- ✅ Trades accumulating steadily
- ✅ PF_local ≥ 1.0 (or trending upward)
- ✅ High-confidence trades outperform low-confidence
- ✅ GPT proposals are modest and rational

**Warning signs:**
- ⚠️ PF_local < 0.9 (triage mode)
- ⚠️ All entries rejected (thresholds too tight)
- ⚠️ All entries accepted (thresholds too loose)
- ⚠️ GPT proposals seem irrational

---

## 💡 Remember

**You've done the hard part:** Wiring, safety, architecture.

**Now it's:** Watch behavior → Let her learn → Use GPT as steering wheel → Iterate.

The system is ready. Let her run and observe.

