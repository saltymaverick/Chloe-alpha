#!/usr/bin/env python3
"""
GPT Council Analysis CLI Tool - Phase 44.3
Manual trigger for GPT-based council performance analysis.
This tool checks conditions and runs analysis if appropriate.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.reflect.gpt_triggers import should_run_gpt_council_analysis
from engine_alpha.reflect.gpt_council_analyzer import run_gpt_council_analysis


def main() -> int:
    """Main entry point for GPT council analysis CLI."""
    if should_run_gpt_council_analysis():
        print("GPT council analysis: conditions met, running...")
        run_gpt_council_analysis()
        return 0
    else:
        print("GPT council analysis: conditions not met, skipping.")
        return 1


if __name__ == "__main__":
    sys.exit(main())


















