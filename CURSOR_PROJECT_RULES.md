# Alpha Chloe — Project Rules (Authoritative)

**Prime Directive:** Survive and profit — survival > risk control > profit.

**Canonical structure (root=/root/engine_alpha):**
- /core (confidence_engine.py, regime.py, chloe_core.py)
- /signals (signal_registry.json, signal_fetchers.py, signal_processor.py)
- /loop (autonomous_trader.py, position_manager.py, exit_engine.py, execute_trade.py)
- /reflect (trade_analysis.py, gpt_reflection.jsonl, reason_score.json, dream_mode.py, dream_log.jsonl)
- /evolve (strategy_evolver.py, strategy_namer.py, strategy_lineage.jsonl, evolver_runs.jsonl)
- /mirror (wallet_hunter.py, wallet_registry.json, wallet_observer.py, mirror_manager.py, mirror_memory.jsonl, strategy_inference.py)
- /dashboard (dashboard.py, dashboard_components.py)
- /config (engine_config.json, risk.yaml, gates.yaml, prompts/*.txt, data_sources.yaml)
- /reports (pf_local.json, pf_live.json, trades.jsonl, incidents.jsonl, news_tone.json, council_snapshot.json, loop_health.json)
- /logs, /data (ohlcv/, sentiment/, onchain/, cache/), /tools, /tests, /builds

**Imports:** Always absolute from package root:
  - ✅ `from engine_alpha.signals import signal_processor`
  - ❌ relative imports

**Defaults:** MODE=PAPER; symbol/timeframe ETHUSDT/15m.
**PA gates:** 0.08/0.05/180. **SAFE MODE:** PF_local<0.95 or 7-loss streak.

**Signal Blueprint (MVP 12):**
Ret_G5, RSI_14, MACD_Hist, VWAP_Dist, ATRp, BB_Width, Vol_Delta, Funding_Bias, OI_Beta, Session_Heat, Event_Cooldown, Spread_Normalized.

**Processor contract:** return dict with keys:
  - `signal_vector: List[float]` (normalized −1..+1, fixed order)
  - `raw_registry: Dict[str,Any]`
  - `ts: ISO8601`

**Council/Regime:**
- Regimes: trend, chop, high_vol.
- ENTRY_MIN_CONF: 0.58/0.64/0.62; EXIT_MIN_CONF: 0.42; reverse on opposite conf ≥0.55.

**Loop order (MUST):** signals → decide → execute_trade → exit_engine.monitor → log_trade → pf_update.

**PF pipeline:** PF_local rolling 100–200 trades; PF_live session; spot-check error ≤1%.

**No unauthorized changes:**
- Do **not** rename files, move folders, invent dependencies, or alter gates without explicit instruction.
- If a spec is missing, ask for the spec; don’t improvise.

**Outputs and artifacts must write to `/reports` and `/logs` only.**

**Tests to pass before merge (minimum):**
- Exit flips, confidence exit, duplicate-entry guard.
- PF recompute order.
- Processor returns non-NaN, correct length, deterministic order.