"""
Autonomous trader - Phase 3
Main trading loop orchestrator.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier
from engine_alpha.loop.position_manager import get_position_manager
from engine_alpha.loop.execute_trade import open_if_allowed
from engine_alpha.loop.exit_engine import monitor
from engine_alpha.reflect.trade_analysis import update_pf_reports


class AutonomousTrader:
    """Main trading loop orchestrator."""
    
    def __init__(self, symbol: str = "ETHUSDT", timeframe: str = "1h"):
        """
        Initialize autonomous trader.
        
        Args:
            symbol: Trading symbol (default: ETHUSDT)
            timeframe: Timeframe (default: 1h)
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.classifier = RegimeClassifier()
        self.trades_path = Path("/reports/trades.jsonl")
        self.pf_local_path = Path("/reports/pf_local.json")
        self.pf_live_path = Path("/reports/pf_live.json")
        
        # Ensure reports directory exists
        self.trades_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _log_trade_event(self, event: Dict[str, Any]) -> None:
        """
        Log trade event to trades.jsonl.
        
        Args:
            event: Trade event dictionary
        """
        with open(self.trades_path, "a") as f:
            f.write(json.dumps(event) + "\n")
    
    def run_step(self) -> Dict[str, Any]:
        """
        Run one trading step.
        
        Returns:
            Diagnostic dictionary
        """
        # Pull signal vector
        signal_result = get_signal_vector(symbol=self.symbol, timeframe=self.timeframe)
        signal_vector = signal_result["signal_vector"]
        raw_registry = signal_result["raw_registry"]
        
        # Get decision
        decision = decide(signal_vector, raw_registry, self.classifier)
        final_dir = decision["final"]["dir"]
        final_conf = decision["final"]["conf"]
        gates = decision["gates"]
        
        # Get current position
        position_manager = get_position_manager()
        position = position_manager.get_open_position()
        
        # Try to open position if allowed
        open_event = None
        if not position_manager.is_open():
            open_event = open_if_allowed(final_dir, final_conf, gates, raw_registry)
            if open_event:
                self._log_trade_event(open_event)
        
        # Monitor for exits/reversals
        exit_event = monitor(decision, raw_registry)
        if exit_event:
            if exit_event.get("event") == "REVERSE":
                # Log close and open separately
                self._log_trade_event(exit_event["close"])
                self._log_trade_event(exit_event["open"])
            else:
                self._log_trade_event(exit_event)
        
        # Update PF reports
        update_pf_reports(self.trades_path, self.pf_local_path, self.pf_live_path)
        
        # Return diagnostics
        return {
            "regime": decision["regime"],
            "final_dir": final_dir,
            "final_conf": final_conf,
            "position": position,
            "open_event": open_event is not None,
            "exit_event": exit_event is not None,
        }
    
    def run_batch(self, n: int = 10) -> Dict[str, Any]:
        """
        Run multiple trading steps.
        
        Args:
            n: Number of steps to run
        
        Returns:
            Summary dictionary
        """
        opens = 0
        closes = 0
        reversals = 0
        
        # Get initial trade count
        initial_trade_count = 0
        if self.trades_path.exists():
            with open(self.trades_path, "r") as f:
                initial_trade_count = sum(1 for line in f if line.strip())
        
        for _ in range(n):
            result = self.run_step()
            if result["open_event"]:
                opens += 1
            if result["exit_event"]:
                closes += 1
        
        # Count reversals from new trades
        if self.trades_path.exists():
            with open(self.trades_path, "r") as f:
                lines = f.readlines()
                # Check new trades (after initial count)
                for line in lines[initial_trade_count:]:
                    try:
                        event = json.loads(line.strip())
                        if event.get("event") == "REVERSE":
                            reversals += 1
                    except:
                        pass
        
        # Read PF values
        pf_local = 1.0
        pf_live = 1.0
        if self.pf_local_path.exists():
            with open(self.pf_local_path, "r") as f:
                pf_local = json.load(f).get("pf", 1.0)
        if self.pf_live_path.exists():
            with open(self.pf_live_path, "r") as f:
                pf_live = json.load(f).get("pf", 1.0)
        
        return {
            "steps": n,
            "opens": opens,
            "closes": closes,
            "reversals": reversals,
            "pf_local": pf_local,
            "pf_live": pf_live,
        }

