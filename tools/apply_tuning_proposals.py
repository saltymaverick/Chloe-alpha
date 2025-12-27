"""
Apply tuning proposals (DRY-RUN only).

This tool reads tuner_output.json and shows what would be changed,
but does NOT modify any live configs. It writes a preview file for inspection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
TUNER_OUTPUT_PATH = GPT_REPORT_DIR / "tuner_output.json"
TUNING_PREVIEW_PATH = GPT_REPORT_DIR / "tuning_preview.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> None:
    tuner_output = load_json(TUNER_OUTPUT_PATH)
    if not tuner_output:
        print(f"❌ tuner_output.json missing or empty at {TUNER_OUTPUT_PATH}")
        return

    # Check both "proposals" (wrapped format) and "tuning_proposals" (legacy format)
    proposals = tuner_output.get("proposals", tuner_output.get("tuning_proposals", {}))
    if not proposals:
        print("⚠️ No tuning_proposals found in tuner_output.json")
        return

    print("CHLOE TUNING PREVIEW (DRY-RUN)")
    print("------------------------------\n")
    print("Note: This does NOT change any live configs.")
    print("      It only summarizes what would be changed if applied.\n")

    preview: Dict[str, Dict[str, Any]] = {}

    for sym, data in proposals.items():
        conf_min_delta = data.get("conf_min_delta", 0.0)
        exploration_cap_delta = data.get("exploration_cap_delta", 0)
        notes = data.get("notes", [])

        # Build human-readable summary for console
        print(f"Symbol: {sym}")
        print(f"  Proposed conf_min delta       : {conf_min_delta:+0.4f}")
        print(f"  Proposed exploration cap delta: {exploration_cap_delta:+d}")
        if notes:
            print("  Notes:")
            for line in notes:
                print(f"    - {line}")
        else:
            print("  Notes: (none)")
        print("")

        # Build machine-readable preview for later application
        preview[sym] = {
            "conf_min_delta": conf_min_delta,
            "exploration_cap_delta": exploration_cap_delta,
            "notes": notes,
        }

    # Write preview JSON so future tools (or you) can inspect/apply manually
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    TUNING_PREVIEW_PATH.write_text(json.dumps(preview, indent=2, sort_keys=True))
    print(f"✅ Tuning preview written to: {TUNING_PREVIEW_PATH}")
    print("   This is still a DRY RUN. No live configs were changed.")


if __name__ == "__main__":
    main()


