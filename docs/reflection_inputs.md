# Chloe Reflection Inputs — Source of Truth

This document defines which JSON artifacts reflections must read so Chloe’s
self-analysis matches her actual live behavior (PF, trades, signals, gates).

Reflections must **not** compute their own thresholds or PFs. They should only
summarize what the engine and analyzers have already written.

---

## 1. Core Files (Ground Truth)

### 1.1 Trades & PF

- `reports/trades.jsonl`
- `reports/scorecards/asset_scorecards.json` (produced by `tools.scorecards`)

Authoritative for:

- total trades per symbol
- wins/losses/scratches
- profit factor (PF)
- average win/loss, max drawdown
- most-used regime / strategy

Reflections must:

- Read PF and trade counts **only** from `asset_scorecards.json` (or the scorecard JSON that `tools.scorecards` writes).
- Never infer PF/trade counts from staleness or other files.

### 1.2 Staleness & Activity

- `reports/research/staleness_overseer.json` (from `tools.staleness_report`)

Per symbol:

- `trading_enabled`, `tier`
- `last_trade_ts`, trades_1d/3d/7d, `total_trades`
- `pf` (may be null if no trades)
- `feed_state`
- `classification` (`new_asset`, `not_enabled`, etc.)
- `suggestion` (`wait_and_observe`, `consider_enabling`, ...)
- `issues` (list of flags)

Use for:

- staleness interpretations (idle vs disabled vs feed issue)
- high-level suggestions (matches overseer classifications)

### 1.3 Market State

- `reports/research/market_state_summary.json` (from `tools.market_state_summary`)

Per symbol:

- `regime`
- trend slopes (`slope5`, `slope20`)
- `atr_rel`
- `feed_state`
- `expect_freq`
- `comment`

Reflections reference this for:

- current market context per asset
- expected trade frequency (“no trades” consistent with chop?)

---

## 2. X-Ray Inputs (Signals & Gates)

### 2.1 Latest Signals

- `reports/debug/latest_signals.json` (written every bar by live loop)

Contains:

- per-asset snapshot with regime, dir, conf, combined_edge, soft_mode flag
- `signals` dict (Ret_G5, RSI_14, MACD, ATRp, RET_1H, Funding_Bias, etc.)

Used for describing recent signal behavior (trend, vol, sentiment).

### 2.2 Signals History

- `reports/debug/signals_history.jsonl`

Raw per-bar history. Used indirectly via `signal_context.json` (below) rather than raw parsing in reflections.

### 2.3 Gate Behavior

- `reports/debug/why_blocked.jsonl`

Each line: symbol, bar_ts, regime, dir, conf, combined_edge, `gate_stage`, `reason`.

Only source of truth for why trades weren’t taken. Summarized via `gate_context.json` (below).

---

## 3. Derived Context (for GPT)

To avoid feeding GPT raw logs, nightly builders produce summarized contexts.

### 3.1 Signal Context

- `reports/research/signal_context.json` (built by `signal_context_builder.py`)

Schema:

```json
{
  "generated_at": "...",
  "timeframe": "15m",
  "assets": {
    "ETHUSDT": {
      "regime_counts": {"trend_up": 10, "trend_down": 24, "chop": 60, "high_vol": 2},
      "avg_conf": 0.27,
      "avg_edge": -0.03,
      "avg_dir": -0.1,
      "avg_atrp": 0.012,
      "avg_ret_1h": 0.001,
      "avg_funding_bias": -0.006,
      "notes": []
    }
  }
}
```

Used by activity/meta reflections to discuss signal strength per asset.

### 3.2 Gate Context

- `reports/research/gate_context.json` (built by `gate_context_builder.py`)

Schema:

```json
{
  "generated_at": "...",
  "timeframe": "15m",
  "assets": {
    "ETHUSDT": {
      "gate_counts": {"regime_gate": 10, "direction": 5, "confidence_gate": 3, "quant_gate": 1},
      "avg_confidence_by_gate": {"confidence_gate": 0.18, "quant_gate": 0.32},
      "avg_edge_by_gate": {"quant_gate": -0.02},
      "last_block": {"ts": "...", "gate_stage": "regime_gate", "reason": "regime_not_allowed", ...}
    }
  }
}
```

Used to summarize which gates block each asset.

### 3.3 Hindsight Reviews

- `reports/research/hindsight_reviews.jsonl` (built by `hindsight_coach.py`)

Each line includes per-trade evaluations (entry/exit grades, suggestions). Used by tuner/meta modules; not required for day-to-day reflections, but available.

---

## 4. Reflection Scripts — Required Inputs

### 4.1 `activity_reflection.py`

Must read **all** of the following when building prompts:

1. `reports/scorecards/asset_scorecards.json` → PF & trade counts
2. `reports/research/staleness_overseer.json` → classification/suggestions
3. `reports/research/market_state_summary.json` → current regime / expected freq
4. `reports/research/signal_context.json` → recent signal strength
5. `reports/research/gate_context.json` → gate block stats

It must not:

- invent PF or thresholds
- infer gate reasons on its own

### 4.2 `activity_meta_reflection.py`

Must consume:

- same inputs as `activity_reflection.py`
- plus `reports/research/activity_reflections.jsonl` (recent memos)
- optionally `reports/research/hindsight_reviews.jsonl` for deeper insights

Goal: multi-day trend summary, not recomputing PF or gates.

---

## 5. Why-No-Trade Explainer

### 5.1 `decision_explainer.py` & `tools/why_no_trade.py`

Use only:

- `reports/debug/why_blocked.jsonl`
- `reports/debug/latest_signals.json`
- `config/regime_thresholds.json`
- `config/observation_mode.json`
- `config/loosen_flags.json`

These produce the authoritative “LIVE GATE VIEW”. GPT narrative must summarize, not recompute, those gate outcomes.

---

With this document tracked in git, Cursor/GPT/devs always know exactly which files each reflection must trust. Adjust reflections to read only these inputs, and the reports will stay consistent with the live scorecards and overseer views.

