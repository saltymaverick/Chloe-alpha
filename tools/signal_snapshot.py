from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS


def _format_float(value) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> None:
    snapshot_path = REPORTS / "debug" / "latest_signals.json"
    if not snapshot_path.exists():
        print("No signal snapshot found yet. Wait for at least one bar.")
        return

    try:
        data = json.loads(snapshot_path.read_text())
    except Exception as exc:
        print(f"Failed to parse snapshot: {exc}")
        return

    if not isinstance(data, dict):
        print("Snapshot file is malformed.")
        return

    generated_at = data.get("generated_at", "unknown")
    print("LATEST SIGNAL SNAPSHOT")
    print("======================")
    print(f"Generated at: {generated_at}\n")

    for symbol, info in data.items():
        if symbol == "generated_at":
            continue
        if not isinstance(info, dict):
            continue
        print(f"{symbol}:")
        print(f"  bar_ts       : {info.get('bar_ts')}")
        print(f"  regime       : {info.get('regime')}")
        conf_val = info.get("conf")
        dir_val = info.get("dir")
        print(f"  dir / conf   : {dir_val} / {_format_float(conf_val)}")
        edge_val = info.get("combined_edge")
        print(f"  combined_edge: {_format_float(edge_val)}")
        soft_mode = info.get("soft_mode")
        if soft_mode is not None:
            print(f"  soft_mode    : {soft_mode}")
        signals = info.get("signals") or {}
        if signals:
            print("  key signals  :")
            for idx, (key, value) in enumerate(signals.items()):
                if idx >= 8:
                    break
                print(f"    - {key}: {_format_float(value)}")
        print()
    print("Done.")


if __name__ == "__main__":
    main()

