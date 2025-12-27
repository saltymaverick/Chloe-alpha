# Master Context Prompt for Chloe Alpha

**Paste this as the first message in Cursor or your AI assistant to establish context.**

---

You are working in the `/root/Chloe-alpha` repo.

This is an algorithmic trading engine for ETHUSDT on 1h candles. The operator (me) has a very clear requirement:

- There must be **ONE unified code path** for live, paper, and backtest.
- Backtests must use the **exact same logic** as live trading (no lab modes, no analysis modes, no forked behavior), except for data source.
- Chloe's goal is **sustainable profit** with sane risk — not max leverage; "profit at all costs" means "we are allowed to be aggressive where we truly have edge."

## Key Components

You'll see these core modules:

- `engine_alpha/loop/autonomous_trader.py`
  - Main trading loop: reads OHLCV, calls signals, decides entries/exits.
  - Runs both live and in backtests.

- `engine_alpha/core/confidence_engine.py`
  - Council of signals: momentum, meanrev, flow, positioning, timing, etc.
  - Aggregates a regime-specific signal vector into final_dir + final_conf.

- `engine_alpha/core/regime.py`
  - Regime classifier: `classify_regime` → `trend_down`, `trend_up`, `high_vol`, `chop`.

- `engine_alpha/loop/execute_trade.py`
  - `_try_open`, `close_now`, wiring into the "wallet" & PnL.

- `config/entry_thresholds.json`
  - Per-regime entry confidence thresholds.

- `tools/signal_return_analyzer.py`
  - Sweeps the entire ETH 1h CSV through Chloe's signal brain.
  - Computes forward returns per (regime × confidence bin).

- `tools/gpt_threshold_tuner.py`
  - Uses that summary and GPT to propose new `entry_thresholds.json`.

- `tools/backtest_harness.py`, `tools/backtest_report.py`, `tools/pf_doctor*.py`
  - Backtest runner + PF analyzers.

- `tools/chloe_checkin.py`, `tools/chloe_auditor.py`
  - Live/paper health, PF, regime breakdown, sanity checks.

## Current Facts

- We fixed the major structural bugs:
  - Backtests and live share the same logic path.
  - `decide()` in `confidence_engine` now uses a **price-based regime** passed from `autonomous_trader`, not a separate regime.
  - Aggregation uses `REGIME_BUCKET_WEIGHTS` consistently.
  - `BACKTEST_FREE_REGIME=1` exists to let backtests ignore the regime gate for analysis-only runs.

- Backtests now **do open and close trades**, but:
  - Almost all trades are in **`chop`** regime.
  - Most exits are **`drop`** or **`decay`** at ~0 pct → classified as scratch.
  - Very few trades reach enough move to count as "meaningful" (|pct| ≥ 0.0005 with exit_reason in {tp, sl}).

- `tools/signal_return_analyzer` shows:
  - `chop`: LOTS of bars; some high-conf bands with PF > 1, but super noisy.
  - `high_vol`: best PF in conf band ~[0.40, 0.45).
  - `trend_down`: limited sample but generally favorable.
  - `trend_up`: one small band with PF > 3.0, but ~28 samples.

- GPT threshold tuner has (so far) **tended to push thresholds up** (more conservative), which reduces trades even more.

## Mode Behavior Requirements

### LIVE/PAPER

**Must:**
- Use regime gate: **only `trend_down` and `high_vol` are allowed to open** for now.
- Use thresholds from `config/entry_thresholds.json` via a single `compute_entry_min_conf(regime, risk_band)` function.
- Not rely on any `LAB_MODE`, `ANALYSIS_MODE`, `BACKTEST_MIN_CONF`, etc.

**Should:**
- Prefer fewer, higher-quality trades.
- Aim for PF ≥ 1.1 over 20+ meaningful closes.

### BACKTEST

**Must:**
- Use the **same trading logic** as live/paper.
- Only difference: OHLCV data comes from CSV via `backtest_harness`.

**May:**
- Temporarily set `BACKTEST_FREE_REGIME=1` so all regimes can open for analysis.

**Should:**
- Write clean `summary.json` and `pf_by_regime` for use by tools like `threshold_tuner`.

## Definitions

- **Scratch trade**: `is_scratch = abs(pct) < 0.0005` and `exit_reason` in {"sl","drop","decay"}. These are noise.

- **Meaningful trade (for PF)**:
  - `|pct| >= threshold` (usually 0.0005),
  - `exit_reason` in {"tp","sl"} (and sometimes "drop" in lab-mode analysis only),
  - `is_scratch == false`.

## What I Want From You

**You are allowed to:**
- Read and refactor code,
- Adjust thresholds logic,
- Improve the GPT tuner prompt / logic,
- Add / improve diagnostic tools.

**You are NOT allowed to:**
- Introduce divergent code paths for backtest vs live.
- Reintroduce any "lab mode / analysis mode" that changes trading behavior.
- Ignore the risk/threshold framework (we want structured, not YOLO).

**Optimization objective:**
- Stable PF > 1.1 in live/paper over 20+ meaningful trades.
- Backtests that actually fire trades and show regime-specific PF that matches our live intuition.

## Reasoning Requirements

You must **always** reason about:

- Regime balance (`trend_down`, `high_vol`, `trend_up`, `chop`),
- Exit behavior (TP/SL vs drop/decay),
- Scratch ratio (we want fewer scratches and more meaningful trades),
- Consistency between live and backtests.

**Use the role prompts I give you next as *tasks* on top of this context.**


