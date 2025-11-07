#!/usr/bin/env python3
"""
Runs the Streamlit dashboard (Phase 10).
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "engine_alpha/dashboard/dashboard.py",
        "--server.port=8501",
        "--server.headless=true",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
