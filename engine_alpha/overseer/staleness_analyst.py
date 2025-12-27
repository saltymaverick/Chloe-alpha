from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS, CONFIG, LOGS

try:
    from engine_alpha.config.assets import load_all_assets
except Exception:  # pragma: no cover - safety fallback
    load_all_assets = None  # type: ignore


DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "ATOMUSDT",
    "BNBUSDT",
    "DOTUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "DOGEUSDT",
]

SCORECARD_PATH = REPORTS / "scorecards" / "asset_scorecards.json"
TRADES_PATH = REPORTS / "trades.jsonl"
TRADING_ENABLEMENT_PATH = CONFIG / "trading_enablement.json"
OVERSEER_REPORT_PATH = REPORTS / "research" / "overseer_report.json"
STALENESS_REPORT_PATH = REPORTS / "research" / "staleness_overseer.json"
LIVE_FEEDS_LOG = LOGS / "live_feeds.log"


@dataclass
class AssetStalenessInfo:
    symbol: str
    tier: Optional[int] = None
    trading_enabled: bool = False
    last_trade_ts: Optional[str] = None
    hours_since_last_trade: Optional[float] = None
    trades_1d: int = 0
    trades_3d: int = 0
    trades_7d: int = 0
    total_trades: int = 0
    pf: Optional[float] = None
    feed_state: str = "unknown"
    issues: List[str] = field(default_factory=list)
    classification: str = "unknown"
    suggestion: str = "wait_and_observe"
    overseer_comment: Optional[str] = None


def _safe_load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def load_symbols() -> List[str]:
    if load_all_assets:
        try:
            assets = load_all_assets()
            symbols = sorted({asset.symbol.upper() for asset in assets})
            if symbols:
                return symbols
        except Exception:
            pass
    return DEFAULT_SYMBOLS


def load_trading_enablement() -> Tuple[str, Dict[str, bool]]:
    data = _safe_load_json(TRADING_ENABLEMENT_PATH)
    phase = data.get("phase", "unknown")
    enabled = {sym.upper(): True for sym in data.get("enabled_for_trading", [])}
    return phase, enabled


def load_scorecards() -> Dict[str, Dict]:
    data = _safe_load_json(SCORECARD_PATH)
    result: Dict[str, Dict] = {}
    for row in data.get("assets", []):
        symbol = row.get("symbol")
        if symbol:
            result[symbol.upper()] = row
    return result


def load_overseer_report() -> Tuple[Dict[str, Dict], Optional[str]]:
    data = _safe_load_json(OVERSEER_REPORT_PATH)
    assets = data.get("assets", {})
    normalized = {sym.upper(): info for sym, info in assets.items()}
    return normalized, data.get("phase")


def parse_live_feeds_log(max_lines: int = 5000) -> Dict[str, str]:
    if not LIVE_FEEDS_LOG.exists():
        return {}
    try:
        lines = LIVE_FEEDS_LOG.read_text().splitlines()
    except Exception:
        return {}
    relevant = lines[-max_lines:]
    states: Dict[str, str] = {}
    for line in relevant:
        symbol = _extract_symbol(line)
        if not symbol:
            continue
        if "LIVE_FEED_OK" in line:
            states[symbol] = "ok"
        elif "LIVE_FEED_STALE" in line:
            states[symbol] = "stale"
        elif "LIVE_FEED_UNAVAILABLE" in line:
            states[symbol] = "unavailable"
        elif "LIVE_FEED_ERROR" in line:
            states.setdefault(symbol, "unknown")
    return states


def _extract_symbol(line: str) -> Optional[str]:
    token = "symbol="
    idx = line.find(token)
    if idx == -1:
        return None
    start = idx + len(token)
    end = line.find(" ", start)
    if end == -1:
        end = len(line)
    return line[start:end].strip().strip(",").upper()


def parse_trades(now: datetime) -> Dict[str, Dict[str, Optional[float]]]:
    if not TRADES_PATH.exists():
        return {}
    per_symbol: defaultdict[str, List[Tuple[datetime, str]]] = defaultdict(list)
    try:
        with TRADES_PATH.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if trade.get("type") != "close":
                    continue
                symbol = trade.get("symbol", "").upper()
                ts_str = trade.get("ts")
                ts_dt = _parse_ts(ts_str)
                if not symbol or not ts_dt:
                    continue
                per_symbol[symbol].append((ts_dt, ts_str))
    except FileNotFoundError:
        return {}

    stats: Dict[str, Dict[str, Optional[float]]] = {}
    for symbol, entries in per_symbol.items():
        entries.sort(key=lambda item: item[0])
        last_dt, last_ts = entries[-1]
        hours_since = (now - last_dt).total_seconds() / 3600.0

        counts = {}
        for days in (1, 3, 7):
            timeframe = timedelta(days=days)
            counts[days] = sum(1 for dt, _ in entries if (now - dt) <= timeframe)

        stats[symbol] = {
            "last_trade_ts": last_ts,
            "hours_since_last_trade": round(hours_since, 2),
            "trades_1d": counts[1],
            "trades_3d": counts[3],
            "trades_7d": counts[7],
            "total_trades": len(entries),
        }
    return stats


def _build_info_for_symbol(
    symbol: str,
    enabled_map: Dict[str, bool],
    scorecards: Dict[str, Dict],
    overseer_assets: Dict[str, Dict],
    feed_states: Dict[str, str],
    trade_stats: Dict[str, Dict[str, Optional[float]]],
) -> AssetStalenessInfo:
    score = scorecards.get(symbol, {})
    overseer = overseer_assets.get(symbol, {})
    trade = trade_stats.get(symbol, {})

    total_trades = score.get("total_trades")
    if total_trades is None:
        total_trades = trade.get("total_trades", 0)

    pf = score.get("pf", overseer.get("pf"))

    info = AssetStalenessInfo(
        symbol=symbol,
        tier=overseer.get("tier"),
        trading_enabled=enabled_map.get(symbol, False),
        last_trade_ts=trade.get("last_trade_ts"),
        hours_since_last_trade=trade.get("hours_since_last_trade"),
        trades_1d=trade.get("trades_1d", 0),
        trades_3d=trade.get("trades_3d", 0),
        trades_7d=trade.get("trades_7d", 0),
        total_trades=int(total_trades) if total_trades is not None else 0,
        pf=pf,
        feed_state=feed_states.get(symbol, "unknown"),
        overseer_comment=overseer.get("overseer_comment"),
    )

    if not info.trading_enabled:
        info.issues.append("trading_disabled")
    if info.feed_state in ("stale", "unavailable"):
        info.issues.append(f"feed_{info.feed_state}")
    if info.total_trades == 0:
        info.issues.append("no_trade_history")

    return info


def classify_staleness(info: AssetStalenessInfo) -> AssetStalenessInfo:
    hours = info.hours_since_last_trade
    pf = info.pf
    total_trades = info.total_trades

    if not info.trading_enabled:
        info.classification = "not_enabled"
        info.suggestion = (
            "consider_enabling"
            if info.feed_state == "ok" and (pf is None or pf >= 1.0)
            else "no_action"
        )
        return info

    if info.feed_state in ("stale", "unavailable"):
        info.classification = "feed_issue"
        info.suggestion = "fix_feed"
        return info

    if total_trades == 0:
        info.classification = "new_asset"
        info.suggestion = "wait_and_observe"
        return info

    if hours is None:
        info.classification = "unknown"
        info.suggestion = "wait_and_observe"
        return info

    if hours < 24:
        info.classification = "no_issue"
        info.suggestion = "no_action"
        return info

    if hours < 72:
        info.classification = "low_activity_edge_ok"
        if pf is not None and pf >= 1.05 and total_trades >= 10:
            info.suggestion = "consider_relaxing_observation_thresholds"
        else:
            info.suggestion = "wait_and_observe"
        return info

    # 72h+
    if pf is not None and pf >= 1.05 and total_trades >= 20:
        info.classification = "maybe_too_strict"
        info.suggestion = "consider_relaxing_observation_thresholds"
    elif pf is not None and pf < 0.9:
        info.classification = "low_activity_edge_ok"
        info.suggestion = "no_action"
    elif info.trades_7d == 0:
        info.classification = "likely_chop"
        info.suggestion = "no_action"
    else:
        info.classification = "low_activity_edge_ok"
        info.suggestion = "monitor_regimes"

    return info


def build_staleness_report(now: Optional[datetime] = None) -> Dict[str, Dict]:
    now = now or datetime.now(timezone.utc)
    symbols = load_symbols()
    phase, enabled_map = load_trading_enablement()
    scorecards = load_scorecards()
    overseer_assets, overseer_phase = load_overseer_report()
    feed_states = parse_live_feeds_log()
    trade_stats = parse_trades(now)

    assets_payload: Dict[str, Dict] = {}
    for symbol in symbols:
        info = _build_info_for_symbol(
            symbol,
            enabled_map,
            scorecards,
            overseer_assets,
            feed_states,
            trade_stats,
        )
        info = classify_staleness(info)
        assets_payload[symbol] = asdict(info)

    report = {
        "generated_at": now.isoformat(),
        "phase": phase,
        "overseer_phase": overseer_phase,
        "assets": assets_payload,
    }

    STALENESS_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STALENESS_REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report


def format_human_report(report: Dict[str, Dict]) -> str:
    lines: List[str] = []
    lines.append("STALENESS REPORT")
    lines.append("-----------------")
    lines.append(f"Phase: {report.get('phase', 'unknown')}")
    lines.append(f"Generated at: {report.get('generated_at', 'N/A')}")
    lines.append("")

    assets = report.get("assets", {})
    def sort_key(item: Tuple[str, Dict]) -> Tuple[int, str]:
        sym, info = item
        enabled = info.get("trading_enabled", False)
        tier = info.get("tier") or 99
        return (0 if enabled else 1, tier, sym)

    for symbol, info in sorted(assets.items(), key=sort_key):
        lines.append(f"{symbol}:")
        lines.append(f"  Trading enabled : {info.get('trading_enabled')}")
        if info.get("tier") is not None:
            lines.append(f"  Tier             : {info.get('tier')}")
        hours = info.get("hours_since_last_trade")
        if hours is None:
            last_line = "N/A"
        else:
            days = round(hours / 24.0, 2)
            last_line = f"{hours:.2f}h (~{days}d) ago"
        lines.append(f"  Last trade       : {info.get('last_trade_ts', 'N/A')} ({last_line})")
        lines.append(
            f"  Trades 1d/3d/7d  : "
            f"{info.get('trades_1d', 0)} / "
            f"{info.get('trades_3d', 0)} / "
            f"{info.get('trades_7d', 0)}"
        )
        pf = info.get("pf")
        lines.append(f"  PF               : {pf if pf is not None else '—'}")
        lines.append(f"  Feed             : {info.get('feed_state', 'unknown')}")
        lines.append(f"  Classification   : {info.get('classification')}")
        lines.append(f"  Suggestion       : {info.get('suggestion')}")
        comment = info.get("overseer_comment")
        if comment:
            lines.append(f"  Overseer comment : {comment}")
        issues = info.get("issues") or []
        if issues:
            lines.append(f"  Issues           : {', '.join(issues)}")
        lines.append("")

    return "\n".join(lines).strip()


__all__ = [
    "AssetStalenessInfo",
    "build_staleness_report",
    "format_human_report",
]

