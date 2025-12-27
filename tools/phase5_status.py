#!/usr/bin/env python3
"""
Phase 5 Status Tool (Phase 5d)
-------------------------------

Quick CLI tool to display the Phase 5 Readiness Panel without running the full dashboard.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure PYTHONPATH includes project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.intel_dashboard import print_phase5_readiness_panel


def main() -> int:
    """Print Phase 5 Readiness Panel."""
    print_phase5_readiness_panel()
    return 0


if __name__ == "__main__":
    sys.exit(main())

