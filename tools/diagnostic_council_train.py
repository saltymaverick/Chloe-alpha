#!/usr/bin/env python3
"""
Council trainer diagnostic - Phase 19
Runs council weight training and prints proposals.
"""

from __future__ import annotations

import json

from engine_alpha.core.council_trainer import run_once
from engine_alpha.core.paths import REPORTS


def main():
    result = run_once()
    for regime, data in result["proposed"].items():
        delta = result["delta"][regime]
        print(f"{regime}: delta={delta} proposed={data}")
    snapshot_path = REPORTS / "council_train_snapshot.json"
    snapshot_path.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
