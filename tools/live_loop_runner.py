#!/usr/bin/env python3
"""
Live loop runner - Multi-Asset Mode

Runs the multi-asset runner to process all enabled assets from asset_registry.json.
Each tick processes all enabled coins and collects candles for them.
"""

from __future__ import annotations

import logging
from engine_alpha.loop.multi_asset_runner import run_all_live_symbols
from engine_alpha.reflect.trade_analysis import update_pf_reports
from engine_alpha.core.paths import REPORTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    """
    Main entry point for live loop runner.
    Processes all enabled assets and updates PF reports.
    """
    try:
        # Run multi-asset runner (processes all enabled coins)
        run_all_live_symbols()
        
        # Update PF reports after processing all assets
        update_pf_reports(
            REPORTS / "trades.jsonl",
            REPORTS / "pf_local.json",
            REPORTS / "pf_live.json",
        )
        
        return 0
    except Exception as exc:
        logger.error(f"LIVE-LOOP: error in multi-asset runner: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())