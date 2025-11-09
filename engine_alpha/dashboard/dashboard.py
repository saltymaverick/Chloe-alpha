"""
Streamlit dashboard - Phase 16
Displays key reports from /reports and /logs.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from engine_alpha.core.paths import REPORTS, LOGS, CONFIG, DATA

from datetime import datetime, timezone

REFRESH_OPTIONS = {"Off": 0, "5 s": 5000, "10 s": 10000, "30 s": 30000}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        # explicit re-read each render (no caching)
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def load_yaml(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f)
            return data or {}
    except Exception:
        return None


def load_jsonl_tail(path: Path, lines: int = 1) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as f:
            rows = f.readlines()[-lines:]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        row = row.strip()
        if not row:
            continue
        try:
            out.append(json.loads(row))
        except Exception:
            continue
    return out


def jsonl_tail(path: Path, lines: int = 1) -> List[Dict[str, Any]]:
    """Alias helper for clarity."""
    return load_jsonl_tail(path, lines)


def load_equity_df() -> Optional[pd.DataFrame]:
    path = REPORTS / "equity_curve.jsonl"
    if not path.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    rows.append(
                        {
                            "ts": pd.to_datetime(obj.get("ts")),
                            "equity": float(obj.get("equity", float("nan"))),
                            "adj_pct": float(obj.get("adj_pct", 0.0)),
                        }
                    )
                except Exception:
                    continue
    except Exception:
        return None
    df = pd.DataFrame(rows).dropna(subset=["ts", "equity"])
    if len(df) < 2:
        return None
    return df.sort_values("ts").tail(300)


def load_backtest_equity_df() -> Optional[pd.DataFrame]:
    path = REPORTS / "backtest" / "equity_curve.jsonl"
    if not path.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r") as f:
            for line in f:
                row = line.strip()
                if not row:
                    continue
                try:
                    obj = json.loads(row)
                    rows.append(
                        {
                            "ts": pd.to_datetime(obj.get("ts")),
                            "equity": float(obj.get("equity", float("nan"))),
                            "adj_pct": float(obj.get("adj_pct", 0.0)),
                        }
                    )
                except Exception:
                    continue
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows).dropna(subset=["ts", "equity"])
    if df.empty:
        return None
    return df.sort_values("ts").tail(300)


def safe_text(path: Path, lines: int = 3) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r") as f:
            return "".join(f.readlines()[-lines:])
    except Exception:
        return ""


def get_value(data: Optional[Dict[str, Any]], *keys, default=None):
    cur: Any = data or {}
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _parse_ts(ts_val: Any) -> Optional[datetime]:
    if ts_val is None:
        return None
    if isinstance(ts_val, (int, float)):
        try:
            return datetime.fromtimestamp(ts_val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts_val, str):
        candidate = ts_val
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            return None
    return None


def fmt_ts(ts_val: Any) -> str:
    dt = _parse_ts(ts_val)
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def color_age(ts_val: Any) -> str:
    dt = _parse_ts(ts_val)
    if dt is None:
        return "gray"
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    if age < 3600:
        return "green"
    if age < 7200:
        return "orange"
    return "red"


def _render_tile(column, label: str, ts_val: Any, extra: Optional[str] = None) -> None:
    color = color_age(ts_val)
    text = fmt_ts(ts_val)
    if extra:
        text = f"{text}  \n{extra}"
    column.markdown(f"**{label}:** :{color}[{text}]")


def _live_defaults() -> Dict[str, str]:
    symbol = "ETHUSDT"
    timeframe = "1h"
    cfg = load_yaml(CONFIG / "backtest.yaml")
    if isinstance(cfg, dict):
        live_cfg = cfg.get("live") or {}
        symbols = live_cfg.get("symbols")
        if isinstance(symbols, list) and symbols:
            symbol = str(symbols[0])
        timeframe = str(live_cfg.get("timeframe", timeframe))
    return {"symbol": symbol, "timeframe": timeframe}


def _load_live_meta(symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    meta_path = DATA / "ohlcv" / f"live_{symbol}_{timeframe}_meta.json"
    return load_json(meta_path)


def _truncate_text(text: str, limit: int = 600) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "…", True


def _extract_trade_ts(trades: List[Dict[str, Any]]) -> Optional[str]:
    for entry in reversed(trades):
        for key in ("ts", "exit_ts", "entry_ts"):
            if entry.get(key):
                return entry.get(key)
    return None


def overview_tab():
    st.header("Overview")

    orch = load_json(REPORTS / "orchestrator_snapshot.json")
    live_state = load_json(REPORTS / "live_loop_state.json")
    trades_tail = jsonl_tail(REPORTS / "trades.jsonl", lines=1)
    dream_tail = jsonl_tail(REPORTS / "dream_log.jsonl", lines=1)

    policy_ts = orch.get("ts") if orch else None
    live_ts = get_value(live_state, "ts")
    trade_ts = _extract_trade_ts(trades_tail)
    dream_ts = dream_tail[0].get("ts") if dream_tail else None

    col_policy, col_live, col_trade, col_dream = st.columns(4)
    _render_tile(col_policy, "Policy", policy_ts)
    live_extra = None
    if live_state:
        sym = live_state.get("symbol")
        tf = live_state.get("timeframe")
        if sym or tf:
            live_extra = f"{sym or ''} {tf or ''}".strip()
    _render_tile(col_live, "Live", live_ts, extra=live_extra or None)
    _render_tile(col_trade, "Trade", trade_ts)
    _render_tile(col_dream, "Dream", dream_ts)

    defaults = _live_defaults()
    meta = _load_live_meta(defaults["symbol"], defaults["timeframe"])
    if meta:
        last_ts = meta.get("last_ts") or meta.get("ts") or "N/A"
        host = meta.get("host") or meta.get("source") or "unknown"
        rows = meta.get("rows") or meta.get("count") or meta.get("size") or "?"
        st.caption(
            f"Live: {defaults['symbol']} {defaults['timeframe']} • last: {fmt_ts(last_ts)} • host: {host} • rows: {rows}"
        )
    else:
        st.caption("Live: N/A")

    pf_local = load_json(REPORTS / "pf_local.json")
    pf_local_adj = load_json(REPORTS / "pf_local_adj.json")
    pa_status = load_json(REPORTS / "pa_status.json")
    equity_tail = load_jsonl_tail(REPORTS / "equity_curve.jsonl", lines=1)
    last_equity = get_value(equity_tail[0], "equity", default="N/A") if equity_tail else "N/A"

    col_pf, col_adj, col_pa, col_equity = st.columns(4)
    col_pf.metric("PF Local", get_value(pf_local, "pf", default="N/A"))
    col_adj.metric("PF Local Adj", get_value(pf_local_adj, "pf", default="N/A"))
    col_pa.metric("PA Armed", str(get_value(pa_status, "armed", default="N/A")))
    col_equity.metric("Last Equity", last_equity)

    policy_inputs = orch.get("inputs", {}) if orch else {}
    policy_flags = orch.get("policy", {}) if orch else {}
    rec = policy_inputs.get("rec", "N/A")
    band = policy_inputs.get("risk_band", "N/A")
    mult = policy_inputs.get("risk_mult", "N/A")
    allow_opens = policy_flags.get("allow_opens") if isinstance(policy_flags.get("allow_opens"), bool) else None
    allow_pa = policy_flags.get("allow_pa") if isinstance(policy_flags.get("allow_pa"), bool) else None

    rec_color = {"GO": "green", "REVIEW": "orange", "PAUSE": "red"}.get(rec, "gray")
    st.markdown("**Policy**")
    st.markdown(f"**REC:** :{rec_color}[{rec}]   **Risk:** {band}   **mult:** {mult}")
    opens_mark = "✅" if allow_opens is True else ("❌" if allow_opens is False else "N/A")
    pa_mark = "✅" if allow_pa is True else ("❌" if allow_pa is False else "N/A")
    st.markdown(f"**Opens:** {opens_mark}   **PA:** {pa_mark}")

    df = load_equity_df()
    if df is not None and not df.empty:
        last_point = df.iloc[-1]
        color = "green" if last_point.get("adj_pct", 0.0) >= 0 else "red"
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)")
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(base + dot, use_container_width=True)
    else:
        st.caption("Equity curve: N/A (need ≥2 points)")

    if st.button("Run Acceptance Check"):
        with st.spinner("Running acceptance check..."):
            try:
                proc = subprocess.run(
                    ["python", "-m", "tools.acceptance_check"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=REPORTS.parent,
                )
                output = proc.stdout.strip() or proc.stderr.strip() or "No output captured"
                try:
                    st.json(json.loads(output))
                except Exception:
                    st.code(output)
            except FileNotFoundError:
                st.error("tools/acceptance_check.py not found")
            except subprocess.TimeoutExpired:
                st.error("Acceptance check timed out")


def portfolio_tab():
    st.header("Portfolio")
    portfolio_dir = REPORTS / "portfolio"

    pf = load_json(portfolio_dir / "portfolio_pf.json")
    health = load_json(portfolio_dir / "portfolio_health.json")
    snapshot = load_json(portfolio_dir / "portfolio_snapshot.json")

    if pf:
        st.metric("Portfolio PF", pf.get("portfolio_pf", "N/A"))
    if health:
        st.write(
            "Health",
            {
                "corr_blocks": health.get("corr_blocks"),
                "exposure_blocks": health.get("exposure_blocks"),
                "net_exposure": sum(health.get("open_positions", {}).values()),
                "cap": get_value(load_json(CONFIG / "asset_list.yaml"), "guard", "net_exposure_cap", default="N/A"),
            },
        )

    symbols = snapshot.get("symbols", []) if snapshot else []
    if not symbols:
        symbols = [p.name.split("_")[0] for p in portfolio_dir.glob("*_trades.jsonl")]

    if symbols:
        cols = st.columns(len(symbols))
        for idx, symbol in enumerate(symbols):
            data = load_json(portfolio_dir / f"{symbol}_pf.json")
            if data:
                cols[idx % len(cols)].metric(symbol, data.get("pf", "N/A"))

    eth_trades = safe_text(portfolio_dir / "ETHUSDT_trades.jsonl", lines=5)
    if eth_trades:
        st.subheader("ETHUSDT trade tail")
        st.code(eth_trades)
    else:
        st.info("No ETHUSDT trades logged yet")


def backtest_tab():
    st.header("Backtest")

    bt_dir = REPORTS / "backtest"

    if st.button("Run Backtest"):
        with st.spinner("Running backtest..."):
            output = ""
            try:
                cmd = [sys.executable, "-m", "tools.run_backtest"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                combined = "\n".join(part for part in [res.stdout.strip(), res.stderr.strip()] if part)
                output = combined or "No output."
            except subprocess.TimeoutExpired:
                output = "Backtest timed out after 120 seconds."
            except Exception as exc:
                output = f"Backtest run failed: {exc}"
            if "ModuleNotFoundError" in output or "ImportError" in output:
                output = f"tools.run_backtest not found\n{output}"
        with st.expander("Backtest Output"):
            st.code(output)
        st.rerun()

    summary = load_json(bt_dir / "summary.json")

    if not summary:
        st.info("No backtest results found under /reports/backtest yet.")
        return

    pf_val = summary.get("pf")
    pf_adj_val = summary.get("pf_adj")
    bars = summary.get("bars")
    trades = summary.get("trades")

    col_pf, col_pf_adj, col_bars, col_trades = st.columns(4)
    col_pf.metric("PF", pf_val if isinstance(pf_val, (int, float)) else pf_val or "N/A")
    col_pf_adj.metric("PF Adj", pf_adj_val if isinstance(pf_adj_val, (int, float)) else pf_adj_val or "N/A")
    col_bars.metric("Bars", bars if isinstance(bars, (int, float)) else bars or "N/A")
    col_trades.metric("Trades", trades if isinstance(trades, (int, float)) else trades or "N/A")

    pf_local_adj = load_json(bt_dir / "pf_local_adj.json")
    if pf_local_adj:
        st.caption(
            f"PF Local Adj: {pf_local_adj.get('pf', 'N/A')} "
            f"(window {pf_local_adj.get('window', 'N/A')}, count {pf_local_adj.get('count', 'N/A')})"
        )

    df = load_backtest_equity_df()
    if df is not None and not df.empty:
        last_point = df.iloc[-1]
        color = "green" if last_point.get("adj_pct", 0.0) >= 0 else "red"
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)")
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(base + dot, use_container_width=True)
    else:
        st.caption("Backtest equity curve unavailable.")

    trades_tail = load_jsonl_tail(bt_dir / "trades.jsonl", lines=20)
    if trades_tail:
        st.subheader("Trades (last 20)")
        try:
            df_trades = pd.DataFrame(trades_tail)
            st.dataframe(df_trades, use_container_width=True)
        except Exception:
            st.code(json.dumps(trades_tail, indent=2))


def intelligence_tab():
    st.header("Intelligence")
    cols = st.columns(3)

    with cols[0]:
        st.subheader("Dream")
        st.json(load_json(REPORTS / "dream_snapshot.json") or {"status": "N/A"})
        dream_tail = load_jsonl_tail(REPORTS / "dream_log.jsonl", 1)
        if dream_tail:
            st.write(dream_tail[0])
    with cols[1]:
        st.subheader("Evolver")
        st.json(load_json(REPORTS / "evolver_snapshot.json") or {"status": "N/A"})
        lineage_tail = load_jsonl_tail(REPORTS / "strategy_lineage.jsonl", 1)
        if lineage_tail:
            st.write(lineage_tail[0])
    with cols[2]:
        st.subheader("Confidence")
        entries = load_jsonl_tail(REPORTS / "confidence_tune.jsonl", 3)
        if entries:
            st.table(entries)
        else:
            st.write("No tune data yet")


def feeds_tab():
    st.header("Feeds & Health")
    snapshot = load_json(REPORTS / "feeds_snapshot.json")
    if snapshot:
        for exchange, data in snapshot.items():
            if exchange == "ts":
                continue
            st.subheader(exchange.upper())
            enabled = data.get("enabled", False)
            st.write("Enabled", enabled)
            if not enabled:
                continue
            time_info = data.get("time", {})
            st.write("Clock skew", time_info.get("clock_skew_ms", "N/A"))
            symbols_info = data.get("symbols", {}).get("symbols", {})
            for symbol, info in symbols_info.items():
                if info.get("ok"):
                    st.success(f"{symbol}: ok ({info.get('latency_ms')} ms)")
                else:
                    st.error(f"{symbol}: {info.get('error', 'fail')}")
    ops_tail = safe_text(LOGS / "ops.log", 3)
    if ops_tail:
        st.subheader("Ops log tail")
        st.code(ops_tail)


def reasoning_tab():
    st.header("Reasoning")
    if "gpt_snapshot_output" in st.session_state:
        with st.expander("GPT Snapshot Output"):
            st.code(st.session_state.pop("gpt_snapshot_output") or "No output captured")

    run_clicked = st.button("Run GPT Snapshot")
    if run_clicked:
        output = ""
        with st.spinner("Running GPT snapshot..."):
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "tools.run_gpt_snapshot"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                parts = [proc.stdout.strip(), proc.stderr.strip()]
                output = "\n".join(part for part in parts if part) or "No output captured"
            except subprocess.TimeoutExpired:
                output = "GPT snapshot timed out after 60 seconds."
            except Exception as exc:  # pragma: no cover
                output = f"GPT snapshot failed: {exc}"
        st.session_state["gpt_snapshot_output"] = output
        st.rerun()

    st.subheader("Reflection Summary")
    reflection = load_json(REPORTS / "gpt_summary.json")
    if reflection:
        text = reflection.get("summary") or ""
        if text:
            preview, truncated = _truncate_text(text)
            st.write(preview)
            if truncated:
                with st.expander("…more"):
                    st.write(text)
        else:
            st.write("Summary: N/A")
        cost = reflection.get("cost_usd")
        tokens = reflection.get("tokens")
        st.caption(f"tokens={tokens or 'N/A'} | cost={cost or 0.0}")
    else:
        st.info("No reflection summary available.")

    st.subheader("News Tone")
    news = load_json(REPORTS / "news_tone.json")
    if news:
        score = news.get("score", "N/A")
        st.write(f"Score: {score}")
        reason = news.get("reason")
        if reason:
            preview, truncated = _truncate_text(str(reason), limit=400)
            st.write(preview)
            if truncated:
                with st.expander("News tone details"):
                    st.write(reason)
    else:
        st.info("No news tone available.")

    st.subheader("Governance Rationale")
    gov_tail = jsonl_tail(REPORTS / "governance_log.jsonl", lines=1)
    if gov_tail:
        record = gov_tail[0]
        rec = record.get("recommendation", "N/A")
        sci = record.get("sci", "N/A")
        st.write(f"Recommendation: {rec} (SCI {sci})")
        reason = record.get("gpt_reason")
        if reason:
            preview, truncated = _truncate_text(str(reason), limit=400)
            st.write(preview)
            if truncated:
                with st.expander("Governance rationale"):
                    st.write(reason)
        else:
            st.write("GPT rationale: N/A")
    else:
        st.info("No governance log entries yet.")


def sandbox_tab():
    st.header("Sandbox")
    runs_path = REPORTS / "sandbox" / "sandbox_runs.jsonl"
    status_path = REPORTS / "sandbox" / "sandbox_status.json"

    if not runs_path.exists() and not status_path.exists():
        st.info("No sandbox data yet")
        return

    runs = load_jsonl_tail(runs_path, lines=5)
    if runs:
        df = pd.DataFrame(runs)
        df = df[[col for col in ["id", "child", "pf_adj", "state", "ts"] if col in df.columns]]
        if not df.empty:
            def highlight(row):
                val = row.get("pf_adj")
                if not isinstance(val, (int, float)):
                    return [""] * len(row)
                if val >= 1.0:
                    color = "background-color: rgba(0,200,0,0.2)"
                elif val >= 0.8:
                    color = "background-color: rgba(255,200,0,0.2)"
                else:
                    color = "background-color: rgba(255,0,0,0.2)"
                return [color] * len(row)
            st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)
    else:
        st.write("No sandbox runs yet")

    status = load_json(status_path)
    if status:
        st.subheader("Status")
        st.json(status)

    if runs:
        last_id = runs[-1].get("id")
        if last_id:
            trades_path = REPORTS / "sandbox" / last_id / "trades.jsonl"
            trades_tail = safe_text(trades_path, lines=3)
            if trades_tail:
                with st.expander("Last run trades tail"):
                    st.code(trades_tail)

    if st.button("Run Sandbox Cycle"):
        with st.spinner("Running sandbox cycle..."):
            try:
                proc = subprocess.run(
                    ["python3", "-m", "engine_alpha.evolve.diagnostic_sandbox", "--steps", "150", "--max-new", "1"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = proc.stdout.strip() or proc.stderr.strip() or "No output captured"
                with st.expander("Sandbox Output"):
                    st.code(output)
            except subprocess.TimeoutExpired:
                st.error("Sandbox cycle timed out")
            except Exception as exc:
                st.error(f"Sandbox cycle failed: {exc}")
            st.rerun()


def main():
    st.set_page_config(page_title="Alpha Chloe Dashboard", layout="wide")
    refresh_choice = st.sidebar.selectbox("Auto-refresh", list(REFRESH_OPTIONS.keys()), index=2)
    if st.sidebar.button("Refresh now"):
        st.rerun()
    st.title("Alpha Chloe Dashboard")
    st.caption("Read-only metrics with health analytics")

    (
        tab_overview,
        tab_portfolio,
        tab_backtest,
        tab_intelligence,
        tab_reasoning,
        tab_feeds,
        tab_sandbox,
    ) = st.tabs(
        ["Overview", "Portfolio", "Backtest", "Intelligence", "Reasoning", "Feeds/Health", "Sandbox"]
    )
    with tab_overview:
        overview_tab()
    with tab_portfolio:
        portfolio_tab()
    with tab_backtest:
        backtest_tab()
    with tab_intelligence:
        intelligence_tab()
    with tab_reasoning:
        reasoning_tab()
    with tab_feeds:
        feeds_tab()
    with tab_sandbox:
        sandbox_tab()

    st.write("Last refresh:", _now())
    try:
        st.query_params = {"ts": str(int(time.time()))}
    except Exception:
        pass

    interval_ms = REFRESH_OPTIONS.get(refresh_choice, 0) or 0
    if interval_ms > 0:
        time.sleep(interval_ms / 1000.0)
        st.rerun()


if __name__ == "__main__":
    main()
