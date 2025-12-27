# engine_alpha/strategies/loader.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

ROOT_DIR = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = ROOT_DIR / "engine_alpha" / "config" / "strategies"


@dataclass
class StrategyConfig:
    name: str
    description: str
    version: int
    status: str
    kind: str
    scope: Dict[str, Any]
    activation: Dict[str, Any]
    entry_logic: Dict[str, Any]
    exit_logic: Dict[str, Any]
    risk: Dict[str, Any]
    tags: List[str]
    path: Path

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_experimental(self) -> bool:
        return self.status == "experimental"


def _load_strategy_file(path: Path) -> Optional[StrategyConfig]:
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        # You can log this instead
        print(f"[strategy_loader] Failed to load {path}: {e}")
        return None

    return StrategyConfig(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        version=int(data.get("version", 1)),
        status=data.get("status", "experimental"),
        kind=data.get("kind", "micro"),
        scope=data.get("scope", {}),
        activation=data.get("activation", {}),
        entry_logic=data.get("entry_logic", {}),
        exit_logic=data.get("exit_logic", {}),
        risk=data.get("risk", {}),
        tags=data.get("tags", []),
        path=path,
    )


def load_all_strategies() -> List[StrategyConfig]:
    """Load all strategy config files from strategies directory."""
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    configs: List[StrategyConfig] = []
    
    for path in STRATEGIES_DIR.glob("*.json"):
        cfg = _load_strategy_file(path)
        if cfg:
            configs.append(cfg)
    
    return configs


def filter_strategies(
    strategies: List[StrategyConfig],
    symbol: str,
    regime: str,
    timeframe: Optional[str] = None,
    direction: Optional[str] = None,
) -> List[StrategyConfig]:
    """
    Return strategies applicable to this symbol/regime/timeframe/direction.
    """
    out: List[StrategyConfig] = []
    
    for s in strategies:
        scope = s.scope
        
        syms = scope.get("symbols") or []
        regs = scope.get("regimes") or []
        tfs = scope.get("timeframes") or []
        dirs = scope.get("direction") or []
        
        if syms and symbol not in syms:
            continue
        if regs and regime not in regs:
            continue
        if timeframe and tfs and timeframe not in tfs:
            continue
        if direction and dirs and direction not in dirs:
            continue
        
        out.append(s)
    
    # Sort by priority descending if present
    out.sort(key=lambda s: s.scope.get("priority", 0), reverse=True)
    
    return out


