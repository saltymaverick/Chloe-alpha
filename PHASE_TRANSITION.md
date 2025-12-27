# Phase Transition: Building → Observing & Steering

## 🎯 Where We Are

**Phase 1: Building** ✅ **COMPLETE**

- Full quant brain wired (signals → regime → drift → confidence → sizing → entry/exit)
- Safety rails in place (dry-run + paper-only)
- GPT risk coach ready (proposes, doesn't override)
- Operational tooling ready (checklists, status scripts)

**Phase 2: Observing & Steering** 🚀 **NOW**

- Let Chloe run in paper mode
- Collect 50-100 trades
- Use GPT tuner to propose threshold adjustments
- Iterate on temperament, not architecture

---

## 🧠 Mental Model Shift

### Before (Building Phase)
**Question:** "Can Chloe even think?"

**Focus:** Wiring, safety, architecture, correctness

**Success Criteria:** System runs end-to-end, dry-run works, entries pass gates

### Now (Observing Phase)
**Question:** "Given how she does think, how do we tune her temperament?"

**Focus:** Behavior, calibration, refinement

**Success Criteria:** PF_local ≥ 1.0, high-confidence trades outperform, GPT proposals are sensible

---

## 🎛️ The Three Temperament Knobs

### 1. Confidence Thresholds = How Picky She Is

- **entry_min_confidence**: Higher = more selective, fewer trades
- **exit_min_confidence**: Lower = holds longer, higher = exits faster

**Current:** entry=0.40, exit=0.30

**GPT will suggest:** Small nudges based on PF_by_confidence_band

---

### 2. Drift Limits = How Quickly She Backs Off

- **max_drift_for_entries**: Higher = trades even when edge is degrading
- **max_drift_for_open_positions**: Higher = holds positions longer during drift

**Current:** entries=0.60, positions=0.70

**GPT will suggest:** Adjustments based on confidence_return_corr and PF trends

---

### 3. Sizing Bands = How Aggressive She Is

- **confidence_bands**: Multipliers for different confidence levels
- **volatility_adjust**: How much vol affects sizing
- **drift_penalty**: How much drift reduces size

**Current:** Configured in `config/risk.yaml` position_sizing section

**GPT will suggest:** (Not yet, but could be added later)

---

## 📊 What to Watch For

### Good Signs ✅
- PF_local trending upward over batches
- High-confidence trades (0.6-1.0) have PF > Low-confidence (0.3-0.6)
- GPT proposals are modest (0.40 → 0.46, not 0.40 → 0.90)
- Rationale aligns with actual stats

### Warning Signs ⚠️
- PF_local < 0.9 consistently
- High-confidence trades losing money
- GPT proposals seem irrational or contradict data
- All entries rejected (too picky) or all accepted (not picky enough)

---

## 🔄 The Iteration Cycle

```
1. Run paper mode → Accumulate 50-100 trades
2. Run GPT tuner → Get proposal
3. Evaluate proposal → Accept or reject
4. If accepted → Update risk.yaml, restart
5. Repeat
```

**Key:** Think in batches (20-30 trades), not individual trades.

---

## 📋 When to Come Back for Interpretation

After you have:
- 50-100 trades accumulated
- GPT tuner proposal generated

Bring:
1. `cat reports/pf_local.json`
2. `tail -1 reports/tuning_proposals.jsonl | jq .`
3. `tail -5 reports/trades.jsonl | jq .`

**Questions to ask:**
- "Is PF_local trash, okay, or promising?"
- "Are high-confidence trades actually better?"
- "Should I accept this GPT proposal?"
- "Is Chloe being cautious, or broken?"

---

## 💡 Remember

**You're no longer building.** You're tuning temperament.

**GPT is your second set of eyes** - it proposes, you decide.

**Think in batches** - don't overreact to individual trades.

**The hard part is done** - now it's observation, learning, and gentle steering.

---

## 🚀 Ready State

- ✅ Architecture complete
- ✅ Safety verified
- ✅ Tooling ready
- ✅ Thresholds set (entry=0.40)
- ✅ Ready for paper run

**Next:** Let her run, collect data, tune, iterate.

