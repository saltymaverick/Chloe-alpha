# Chloe Alpha Quant Dashboard — Specification

## Goals

- Provide a professional, quant-style dashboard for monitoring Chloe.
- Support both operators (you) and quants/engineers.
- Make it trivial for quants to add new panels or metrics.
- Read-only interface over Chloe's state: reports, logs, and SWARM supervision.

## Tech Stack

- Python 3.x
- Streamlit
- Pandas, Plotly (optional for charts)
- File-based data from:
  - `reports/`
  - `reports/research/`
  - `logs/`
  - `data/ohlcv/`

## Panels

1. **Home Panel (Overview)**
   - PF_local, drawdown, avg_edge (from `pf_local.json` and `loop_health.json`).
   - Simple PnL/time chart.
   - SWARM overall status (from `swarm_sentinel_report.json`).

2. **Live Panel (Trade Blotter)**
   - Recent trades from `reports/trades.jsonl` (or `trade_log.jsonl`).
   - Current position summary (if present in reports).
   - Basic price/time chart using recent candles.

3. **Research Panel**
   - Info from:
     - `reports/research/multi_horizon_stats.json`
     - `reports/research/strategy_strength.json`
     - `config/confidence_map.json`
     - `config/regime_thresholds.json`
   - Show strategy strength table, confidence map, and thresholds.

4. **SWARM Panel**
   - Sentinel snapshot from `swarm_sentinel_report.json`.
   - Recent audit entries from `swarm_audit_log.jsonl`.
   - Recent research verification from `swarm_research_verifier.jsonl`.
   - Recent challenger decisions from `swarm_challenger_log.jsonl`.

5. **Risk Panel**
   - PF_local, drawdown, risk multipliers and notional limits (when available).
   - Exposure summary from trades.

6. **Wallet Panel**
   - Wallet mode (paper/real) from `wallet_config.json`.
   - Credential presence from `load_real_exchange_keys`.
   - Notional limits and safety flags.

7. **Operator Panel**
   - Information-only for now:
   - Shows recommended commands and current important toggles.

8. **System Panel**
   - Basic filesystem & freshness checks:
     - Last `swarm_audit` time.
     - Last `nightly_research` run (based on file mtimes).
     - Log file list and sizes.

## Layout

- Single Streamlit app: `engine_alpha/dashboard/dashboard.py`.
- Left sidebar: panel selector.
- Each panel in `engine_alpha/dashboard/<name>_panel.py` with a top-level `render()` function.
- Shared visual helpers in `engine_alpha/dashboard/components/`.

## Extensibility

- New panels: add `<panel_name>_panel.py` with `render()`, register in `dashboard.py`.
- New metrics: expose them in JSON in `reports/` or `reports/research/` and read them in the relevant panel.

## Security

- Dashboard is read-only: no direct trade execution or config changes from UI.
- Control path (CLI/operator) remains separate.


