# Chloe Validation Checklist - Pro-Quant Risk Stack

Run through these checks in **PAPER mode** before considering live trading.

## ✅ 1. Nightly Research Pipeline

### Run nightly research:
```bash
python3 -m engine_alpha.reflect.nightly_research
```

### Verify these files update:

- [ ] `reports/research/hybrid_research_dataset.parquet`
  - Check: `ls -lh reports/research/hybrid_research_dataset.parquet`
  - Should exist and have recent timestamp

- [ ] `reports/research/multi_horizon_stats.json`
  - Check: `cat reports/research/multi_horizon_stats.json | head -20`
  - Should contain regime × confidence bin stats

- [ ] `reports/research/strategy_strength.json`
  - Check: `cat reports/research/strategy_strength.json`
  - Should have regime strength/edge/hit_rate per regime

- [ ] `config/entry_thresholds.json` (if tuner ran)
  - Check: `cat config/entry_thresholds.json`
  - Should have per-regime thresholds

- [ ] `config/regime_enable.json` (if tuner ran)
  - Check: `cat config/regime_enable.json`
  - Should have enable flags per regime

- [ ] `config/confidence_map.json` (optional, for edge lookup)
  - Check: `cat config/confidence_map.json`
  - Maps confidence buckets to expected returns

- [ ] `reports/loop_health.json`
  - Check: `cat reports/loop_health.json`
  - Should have: `pf_local`, `drawdown`, `avg_edge`, `blind_spots`

- [ ] `reports/council_snapshot.json`
  - Check: `cat reports/council_snapshot.json`
  - Should have: `top_regimes`, `worst_regimes`

### Expected output:
```
✅ Trade outcomes at reports/research/trade_outcomes.jsonl
✅ Hybrid dataset at reports/research/hybrid_research_dataset.parquet
✅ Analyzer stats at reports/research/multi_horizon_stats.json
✅ Quant monitor tiles updated
```

---

## ✅ 2. Gate & Size Trade Integration

### Verify gate_and_size_trade is being called:

- [ ] Enable debug logging:
  ```bash
  export DEBUG_SIGNALS=1
  ```

- [ ] Run live loop (paper mode):
  ```bash
  python3 -m tools.live_loop_runner  # or your live loop command
  ```

- [ ] Tail logs and look for:
  ```
  QUANT-GATE: Trade allowed (notional=X): ...
  QUANT-GATE: Trade blocked: ...
  ```

### Verify behavior:

- [ ] **Some trades are blocked** (not all allowed)
  - If all trades pass, sanity gates may be too loose

- [ ] **Some trades are allowed** (not all blocked)
  - If all trades blocked, gates may be too strict

- [ ] **Block reasons are logged**:
  - "PF_local=X below hard block Y"
  - "Regime X has strong negative strength"
  - "Blind spot flagged and confidence < 0.5"
  - "Blocked: combined edge < -0.0005"

- [ ] **Allow reasons are logged**:
  - "Allowed: sanity=ok, edge=X, pa_mult=Y"

---

## ✅ 3. PF & Drawdown Wiring

### Check pf_local.json updates:

- [ ] File exists:
  ```bash
  cat reports/pf_local.json
  ```

- [ ] Contains expected fields:
  ```json
  {
    "pf": 1.05,
    "drawdown": 0.02
  }
  ```

- [ ] Updates after trades:
  ```bash
  # Before trade
  cat reports/pf_local.json
  
  # Run a few trades
  
  # After trade
  cat reports/pf_local.json
  # PF should change if trades were profitable/losing
  ```

### Verify PF calculation:

- [ ] PF increases after winning trades
- [ ] PF decreases after losing trades
- [ ] Drawdown field exists (even if simple for now)

---

## ✅ 4. Position Size Behavior

### Log position sizing:

Add temporary logging to see base vs final notional:

```python
# In autonomous_trader.py, after gate_and_size_trade:
if DEBUG_SIGNALS:
    print(f"POSITION-SIZE: base={base_notional:.4f} final={final_notional:.4f} mult={final_notional/base_notional:.2f}x")
```

### Verify patterns:

- [ ] **Good conditions** (PF > 1.1, low DD, high conf):
  - Multiplier should be >= 1.0 (may go up to 1.2x)

- [ ] **Bad conditions** (PF < 0.95, high DD, low conf):
  - Multiplier should be < 1.0 (may go down to 0.7x)

- [ ] **High volatility** (ATR > 0.04):
  - Multiplier should contract (0.6x - 0.8x)

- [ ] **No insane spikes**:
  - Final notional should never exceed 2x base
  - Final notional should never go below 0.2x base

---

## ✅ 5. Sanity Gate Behavior

### Test scenarios:

- [ ] **Low PF scenario**:
  - Manually set `pf_local.json` to `{"pf": 0.80, "drawdown": 0.05}`
  - Run live loop
  - Should see: "QUANT-GATE: Trade blocked: PF_local=0.80 below hard block 0.85"

- [ ] **Negative regime strength**:
  - Manually set `strategy_strength.json` with negative strength for a regime
  - Run live loop in that regime
  - Should see: "QUANT-GATE: Trade blocked: Regime X has strong negative strength"

- [ ] **Blind spot + low confidence**:
  - Create `reports/research/blind_spots.jsonl` with one entry
  - Run live loop with confidence < 0.5
  - Should see: "QUANT-GATE: Trade blocked: Blind spot flagged and confidence < 0.5"

---

## ✅ 6. Quant Monitor Tiles

### Check tiles update:

- [ ] After nightly research:
  ```bash
  cat reports/loop_health.json
  cat reports/council_snapshot.json
  ```

- [ ] Values are reasonable:
  - `pf_local`: Should be between 0.5 and 2.0 (roughly)
  - `drawdown`: Should be between 0.0 and 0.5 (roughly)
  - `avg_edge`: Should be between -0.01 and 0.01 (roughly)
  - `blind_spots`: Should be integer >= 0

- [ ] Regimes are listed:
  - `top_regimes`: Should have 1-5 regimes
  - `worst_regimes`: Should have 1-5 regimes

---

## ✅ 7. Integration Smoke Test

### Run a short paper session:

```bash
# Set paper mode
export MODE=PAPER
export DEBUG_SIGNALS=1

# Run for ~10-20 bars
python3 -m tools.live_loop_runner  # or your command
```

### Verify:

- [ ] No crashes or exceptions
- [ ] Trades are logged to `reports/trades.jsonl`
- [ ] PF updates after closes
- [ ] Quant gates are being hit (check logs)
- [ ] Position sizes look sane

---

## ✅ 8. Configuration Files

### Verify all configs exist (or have defaults):

- [ ] `config/entry_thresholds.json` - Per-regime entry thresholds
- [ ] `config/regime_enable.json` - Regime enable flags
- [ ] `config/exit_rules.json` - Per-regime exit rules
- [ ] `config/gates.yaml` - Profit Amplifier config
- [ ] `config/research_weights.json` - Research weighting config
- [ ] `config/risk.yaml` - Risk config (optional, for base_notional_pct)

---

## ✅ Checklist Summary

- [ ] Nightly research runs clean
- [ ] All expected files update
- [ ] gate_and_size_trade is being called
- [ ] Some trades blocked, some allowed
- [ ] PF & drawdown update correctly
- [ ] Position sizes scale appropriately
- [ ] Sanity gates block when expected
- [ ] Quant monitor tiles update
- [ ] No crashes in paper mode
- [ ] All config files exist or have defaults

---

## 🚨 Red Flags (Stop if you see these)

- ❌ All trades blocked (gates too strict)
- ❌ All trades allowed (gates not working)
- ❌ Position sizes > 2x base (risk multiplier broken)
- ❌ Position sizes < 0.2x base consistently (too conservative)
- ❌ PF not updating (PF calculation broken)
- ❌ Crashes or exceptions in live loop
- ❌ Quant monitor tiles not updating

---

## ✅ Green Lights (Ready for paper burn)

- ✅ Nightly research completes successfully
- ✅ Mix of blocked/allowed trades
- ✅ Position sizes scale with conditions
- ✅ PF updates correctly
- ✅ Sanity gates block appropriately
- ✅ No crashes or exceptions
- ✅ All configs in place

**If all green lights, proceed to paper-burn experiment.**


