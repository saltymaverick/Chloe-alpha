# engine_alpha/loop/multi_asset_runner.py

from __future__ import annotations

from typing import List
from datetime import datetime, timezone
import logging

from engine_alpha.config.assets import get_enabled_assets
from engine_alpha.config.trading_enablement import is_trading_enabled, get_current_phase
from engine_alpha.loop.autonomous_trader import run_step_live

logger = logging.getLogger(__name__)


def run_all_live_symbols():
    """
    Iterate over all enabled assets and call run_step_live for each.
    
    Only assets enabled for trading (via trading_enablement.json) will execute trades.
    All assets enabled in asset_registry.json will still collect data and run research.
    
    Note: Symbol Registry (config/symbols.yaml) can also be used via:
    from engine_alpha.core.symbol_registry import load_symbol_registry
    enabled_symbols = load_symbol_registry()
    
    Assumes run_step_live can accept (symbol, timeframe) as arguments.
    """
    assets = get_enabled_assets()
    
    if not assets:
        logger.warning("MULTI-ASSET: No enabled assets in asset_registry.json")
        # Fallback: try Symbol Registry
        try:
            from engine_alpha.core.symbol_registry import load_symbol_registry
            enabled_symbols = load_symbol_registry()
            if enabled_symbols:
                logger.info(f"MULTI-ASSET: Found {len(enabled_symbols)} symbols in Symbol Registry")
                # Note: Symbol Registry doesn't provide timeframe, so we'd need to map to asset_registry
                # For now, we'll just log and continue with empty assets
        except Exception as e:
            logger.debug(f"MULTI-ASSET: Symbol Registry fallback failed: {e}")
        return
    
    trading_enabled = {asset.symbol for asset in assets if is_trading_enabled(asset.symbol)}
    phase = get_current_phase()
    
    now = datetime.now(timezone.utc).isoformat()
    logger.info(
        "MULTI-ASSET: tick at %s for %d assets (phase: %s, trading: %d)",
        now, len(assets), phase, len(trading_enabled)
    )
    
    for asset in assets:
        # Check trading enablement: only trading-enabled assets execute trades
        if not is_trading_enabled(asset.symbol):
            logger.debug(
                "MULTI-ASSET: %s skipped (data collection only, not trading-enabled)",
                asset.symbol
            )
            continue
        
        try:
            logger.info(
                "MULTI-ASSET: running live step for %s @ %s",
                asset.symbol,
                asset.base_timeframe,
            )
            # Ensure your run_step_live signature matches this
            run_step_live(symbol=asset.symbol, timeframe=asset.base_timeframe)
        except TypeError:
            # Fallback: if your run_step_live currently takes no args, just call it
            logger.warning(
                "MULTI-ASSET: run_step_live() does not accept symbol/timeframe yet; calling without args"
            )
            run_step_live()
        except Exception as e:
            logger.error(
                "MULTI-ASSET: error in run_step_live for %s@%s: %s",
                asset.symbol,
                asset.base_timeframe,
                e,
                exc_info=True,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_all_live_symbols()

