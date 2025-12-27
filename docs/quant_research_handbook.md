# Quant Research Handbook — Chloe Alpha

This document explains how Chloe's research engine works, how edge is derived, how PF evolves, and how SWARM supervises the learning pipeline.

---

## 📘 Pipeline Summary

Every night, Chloe runs:

1. **Trade Outcome Builder**
2. **Hybrid Dataset Builder**
3. **Weighted Analyzer**
4. **Weighted Tuner**
5. **Confidence Map Builder**
6. **Strategy Strength Calculator**
7. **Auto-Promotion / Pruning**
8. **Profit Amplifier Coupling**
9. **Blind Spot Detection**
10. **SWARM Research Verification**
11. **SWARM Sentinel Snapshot**
12. **Quant Monitor Tiles**

---

## 📈 1. Trade Outcomes

Reads:
- `reports/trades.jsonl`
- `reports/trade_log.jsonl`

Outputs:
- `reports/research/trade_outcomes.jsonl`

Used for:
- Forward return estimation
- Regime-based performance
- Entry/exit real-world behavior

---

## 📊 2. Hybrid Dataset

Combines:
- Static historical OHLCV (optional)
- Live candles (from `live_candle_collector`)
- Trade outcomes

Outputs Parquet:
- `hybrid_research_dataset.parquet`

Adds forward returns:
- `ret_1h`
- `ret_2h`
- `ret_4h`

---

## 🧠 3. Weighted Analyzer

Uses:
- Recency weighting (half-life)
- Source weighting (live > static)
- Regime × confidence buckets

Outputs:
- `multi_horizon_stats.json`

This is Chloe's **empirical expected return map**.

---

## 🔧 4. Weighted Tuner

Uses analyzer output to adjust:
- Regime enable flags
- Entry `entry_min_conf` thresholds

Applies step limits and guardrails.

Output:
- `entry_thresholds.json`
- `regime_enable.json`

---

## 🎯 5. Confidence Map

Maps confidence bucket → expected return.

Output:
- `confidence_map.json`

Used by:
- Risk engine
- `gate_and_size_trade`
- Challenger
- Dashboard

---

## 💪 6. Strategy Strength

Computes:
```
strength = edge * hit_rate * log(1 + weighted_count)
```

Output:
- `strategy_strength.json`

---

## 🔥 7. Auto-Promotion / Pruning

Uses strategy strength to:
- Lower thresholds on strong regimes
- Tighten or disable weak regimes

Logged in:
- `promotion_log.jsonl`

---

## 📉 8. Profit Amplifier Coupling

Adjusts target PF based on global edge.

---

## 🕳️ 9. Blind Spot Detection

Flags:
- Empty buckets
- Under-sampled regimes

Logs to:
- `blind_spots.jsonl`

---

## 🧪 10–12. SWARM Supervision

SWARM watches:
- Consistency
- Health
- Alignment
- Missing data
- Overly conservative behavior
- Challenger disagreements

Visualized in dashboard.

---

## 🧩 Summary

Chloe's research engine evolves her expected return model, confidence calibration, regime thresholds, risk profile, and sanity gating. SWARM ensures no silent failure ever corrupts her logic.

This is a fully professional quant research loop.


