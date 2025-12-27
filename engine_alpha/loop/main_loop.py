#!/usr/bin/env python3
"""
Main trading loop entrypoint for systemd service.

Runs run_step_live() continuously with proper error handling.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from engine_alpha.loop.autonomous_trader import run_step_live
from engine_alpha.core.paths import CONFIG
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default config
DEFAULT_SYMBOL = "ETHUSDT"
DEFAULT_TIMEFRAME = "1h"
DEFAULT_TICK_INTERVAL_SECONDS = 60  # Run every 60 seconds


def load_loop_config() -> Dict[str, Any]:
    """Load loop configuration from engine_config.json."""
    config_path = CONFIG / "engine_config.json"
    defaults = {
        "loop_sleep_s": DEFAULT_TICK_INTERVAL_SECONDS,
    }
    
    if not config_path.exists():
        return defaults
    
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {
                "loop_sleep_s": data.get("loop_sleep_s", DEFAULT_TICK_INTERVAL_SECONDS),
            }
    except Exception:
        pass
    
    return defaults


def main_loop(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    tick_interval: int = None,
):
    """
    Main trading loop - runs continuously.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
        tick_interval: Seconds between ticks (None = load from config)
    """
    # Load tick interval from config if not provided
    if tick_interval is None:
        loop_cfg = load_loop_config()
        tick_interval = loop_cfg.get("loop_sleep_s", DEFAULT_TICK_INTERVAL_SECONDS)
    
    logger.info(f"Starting main loop: symbol={symbol}, timeframe={timeframe}, interval={tick_interval}s")
    
    consecutive_errors = 0
    max_consecutive_errors = 10
    
    while True:
        try:
            # Run one tick
            run_step_live(
                symbol=symbol,
                timeframe=timeframe,
                limit=200,
            )
            
            # Reset error counter on success
            consecutive_errors = 0
            
            # Sleep until next tick
            time.sleep(tick_interval)
            
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt - shutting down gracefully")
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(
                f"Error in main loop (consecutive={consecutive_errors}): {type(e).__name__}: {e}",
                exc_info=True
            )
            
            # If too many consecutive errors, exit to let systemd handle restart
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"Too many consecutive errors ({consecutive_errors}) - exiting")
                raise
            
            # Wait before retrying (exponential backoff)
            wait_time = min(tick_interval * (2 ** min(consecutive_errors, 3)), 300)
            logger.info(f"Waiting {wait_time}s before retry")
            time.sleep(wait_time)


if __name__ == "__main__":
    import sys
    
    # Parse command line args (optional)
    symbol = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    timeframe = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TIMEFRAME
    tick_interval = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_TICK_INTERVAL_SECONDS
    
    try:
        main_loop(symbol=symbol, timeframe=timeframe, tick_interval=tick_interval)
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        sys.exit(1)

