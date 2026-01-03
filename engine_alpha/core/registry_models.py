# engine_alpha/core/registry_models.py
# Canonical Pydantic schemas for:
# - config/asset_registry.json
# - config/lane_registry.json
#
# Designed for: strict validation + forward-compatible extensions.

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


# ----------------------------
# Shared
# ----------------------------

class Venue(str, Enum):
    binance = "binance"
    bybit = "bybit"
    okx = "okx"
    coinbase = "coinbase"


class SymbolClass(str, Enum):
    major = "major"
    large = "large"
    mid = "mid"
    meme = "meme"
    unknown = "unknown"


class Timeframe(str, Enum):
    # extend as needed
    m1 = "1m"
    m3 = "3m"
    m5 = "5m"
    m15 = "15m"
    m30 = "30m"
    h1 = "1h"
    h4 = "4h"
    d1 = "1d"


# ----------------------------
# Asset registry
# ----------------------------

class SymbolCaps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_positions: int = Field(1, ge=0)
    risk_mult_cap: float = Field(0.25, ge=0.0, le=10.0)


class SymbolDefaults(BaseModel):
    """
    Defaults ONLY. Your symbol_state_builder may override.
    Keep fields stable so UI + builder can rely on presence.
    """
    model_config = ConfigDict(extra="forbid")

    allow_core: bool = True
    allow_exploration: bool = True
    allow_scalp: bool = True
    allow_expansion: bool = True
    allow_recovery: bool = True


class AssetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    class_: SymbolClass = Field(SymbolClass.unknown, alias="class")

    base_timeframe: Timeframe = Timeframe.h1
    venue: Venue = Venue.binance

    tags: List[str] = Field(default_factory=list)

    defaults: SymbolDefaults = Field(default_factory=SymbolDefaults)
    caps: SymbolCaps = Field(default_factory=SymbolCaps)

    # Optional per-symbol metadata (explicit for strict validation)
    symbol: Optional[str] = None  # Redundant with key, but allowed for clarity
    quote_ccy: Optional[str] = Field(default=None)
    max_leverage: Optional[float] = Field(default=None, ge=1.0, le=125.0)
    min_notional_usd: Optional[float] = Field(default=None, ge=0.0)
    notes: Optional[str] = None


class AssetRegistry(RootModel[Dict[str, AssetConfig]]):
    """
    JSON format:
    {
      "ADAUSDT": { ...AssetConfig... },
      "BTCUSDT": { ...AssetConfig... }
    }
    """
    root: Dict[str, AssetConfig]

    @field_validator("root")
    @classmethod
    def validate_symbol_keys(cls, v: Dict[str, AssetConfig]) -> Dict[str, AssetConfig]:
        if not v:
            raise ValueError("asset_registry is empty")
        for sym in v.keys():
            if not isinstance(sym, str) or len(sym) < 3:
                raise ValueError(f"invalid symbol key: {sym!r}")
            # normalize expectation: uppercase keys
            if sym != sym.upper():
                raise ValueError(f"symbol key must be uppercase: {sym!r}")
        return v


# ----------------------------
# Lane registry
# ----------------------------

class EvalType(str, Enum):
    pf = "pf"
    edge_per_hour = "edge_per_hour"
    counterfactual = "counterfactual"


class LaneEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EvalType = EvalType.pf
    min_closes: int = Field(0, ge=0)
    min_outcomes: int = Field(0, ge=0)

    # Optional thresholds (lane-specific dashboards can use these)
    min_pf: Optional[float] = None
    min_edge_per_hour: Optional[float] = None


class LaneRiskProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_mult: float = Field(1.0, ge=0.0, le=10.0)

    # Discipline
    min_hold_s: int = Field(0, ge=0)
    cooldown_s: int = Field(0, ge=0)

    # Optional percent-based exits for lanes that use them
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None

    # Hard caps
    max_trades_per_24h: Optional[int] = Field(default=None, ge=0)
    max_open_positions_per_symbol: Optional[int] = Field(default=None, ge=0)


class LaneRequires(BaseModel):
    """
    Eligibility "inputs" used by resolver.
    Keep this declarative; lane code can be more nuanced.
    """
    model_config = ConfigDict(extra="forbid")

    regimes: List[str] = Field(default_factory=list)         # e.g. ["trend_up","trend_down","high_vol"]
    micro_regimes: List[str] = Field(default_factory=list)   # e.g. ["active_chop","failed_break"]
    min_conf: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Common boolean toggles
    require_expansion_event: bool = False
    block_dead_chop: bool = False


class LaneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    # This must match your lane implementation LANE_ID.
    lane_id: str = Field(..., min_length=2)
    
    # Priority for lane ordering (lower = higher priority)
    priority: int = Field(default=100, ge=0)

    # Human-readable (dashboard)
    title: str = Field(..., min_length=2)
    purpose: str = Field(..., min_length=2)

    risk: LaneRiskProfile = Field(default_factory=LaneRiskProfile)
    evaluation: LaneEvaluation = Field(default_factory=LaneEvaluation)
    requires: LaneRequires = Field(default_factory=LaneRequires)

    # Optional: UI hints
    color: Optional[str] = None  # e.g. "purple" (UI-only, not logic)
    icon: Optional[str] = None   # e.g. "zap" (UI-only, not logic)


class LaneRegistry(RootModel[Dict[str, LaneConfig]]):
    """
    JSON format:
    {
      "core": { "lane_id": "core", ... },
      "scalp": { "lane_id": "scalp", ... }
    }
    Root keys are "lane keys" used for ordering and display.
    `lane_id` must equal the key (enforced below).
    """
    root: Dict[str, LaneConfig]

    @field_validator("root")
    @classmethod
    def validate_lane_keys_match_lane_id(cls, v: Dict[str, LaneConfig]) -> Dict[str, LaneConfig]:
        if not v:
            raise ValueError("lane_registry is empty")
        for key, cfg in v.items():
            if key != cfg.lane_id:
                raise ValueError(f"lane key '{key}' must match lane_id '{cfg.lane_id}'")
        return v


# ----------------------------
# Loader helpers
# ----------------------------

def load_asset_registry(path: str) -> AssetRegistry:
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AssetRegistry.model_validate(data)


def load_lane_registry(path: str) -> LaneRegistry:
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return LaneRegistry.model_validate(data)

