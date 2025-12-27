"""
Pydantic models for Chloe Alpha API responses.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health status response."""
    last_tick_ts: Optional[str] = None
    ok: Optional[bool] = None
    issues: Optional[List[str]] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: __import__('datetime').datetime.now().isoformat())


class FileInfo(BaseModel):
    """File information model."""
    path: str
    size_bytes: int
    modified_timestamp: float
    modified_iso: str


class MetaLogSizesResponse(BaseModel):
    """Meta log sizes response."""
    counterfactual: Optional[FileInfo] = None
    inaction: Optional[FileInfo] = None
    fvg: Optional[FileInfo] = None
    opportunity_events: Optional[FileInfo] = None


class TradeEntry(BaseModel):
    """Trade entry model (flexible for various trade formats)."""
    ts: Optional[str] = None
    symbol: Optional[str] = None
    type: Optional[str] = None
    exit_reason: Optional[str] = None
    pct: Optional[float] = None
    entry_px: Optional[float] = None
    exit_px: Optional[float] = None
    regime: Optional[str] = None
    trade_kind: Optional[str] = None
    exit_px_source: Optional[str] = None
    risk_mult: Optional[float] = None


class PfResponse(BaseModel):
    """PF (Profit Factor) data response."""
    pf: Optional[float] = None
    window: Optional[int] = None
    count: Optional[int] = None
    generated_at: Optional[str] = None
    pf_24h: Optional[float] = None
    count_24h: Optional[int] = None
    scratch_only_24h: Optional[bool] = None
    scratch_count_24h: Optional[int] = None
    lossless_24h: Optional[bool] = None
    gross_profit_24h: Optional[float] = None
    gross_loss_24h: Optional[float] = None
    regime_accuracy_unknown: Optional[float] = None
    regime_samples_unknown: Optional[int] = None
    regime_accuracy_chop: Optional[float] = None
    regime_samples_chop: Optional[int] = None
    regime_accuracy_trend_up: Optional[float] = None
    regime_samples_trend_up: Optional[int] = None
    regime_accuracy_trend_down: Optional[float] = None
    regime_samples_trend_down: Optional[int] = None
    regime_accuracy_total_samples: Optional[int] = None
    pf_24h_ex_bootstrap_timeouts: Optional[float] = None
    count_24h_ex_bootstrap_timeouts: Optional[int] = None
    scratch_only_24h_ex_bootstrap_timeouts: Optional[bool] = None
    gross_profit_24h_ex_bootstrap_timeouts: Optional[float] = None
    gross_loss_24h_ex_bootstrap_timeouts: Optional[float] = None
    lossless_24h_ex_bootstrap_timeouts: Optional[bool] = None
    pf_24h_ex_bootstrap: Optional[float] = None
    count_24h_ex_bootstrap: Optional[int] = None
    pf_7d: Optional[float] = None
    count_7d: Optional[int] = None
    scratch_only_7d: Optional[bool] = None
    scratch_count_7d: Optional[int] = None
    lossless_7d: Optional[bool] = None
    gross_profit_7d: Optional[float] = None
    gross_loss_7d: Optional[float] = None
    pf_7d_regime_chop: Optional[float] = None
    count_7d_regime_chop: Optional[int] = None
    gross_profit_7d_regime_chop: Optional[float] = None
    gross_loss_7d_regime_chop: Optional[float] = None
    pf_7d_regime_trend_up: Optional[float] = None
    count_7d_regime_trend_up: Optional[int] = None
    gross_profit_7d_regime_trend_up: Optional[float] = None
    gross_loss_7d_regime_trend_up: Optional[float] = None
    pf_7d_regime_trend_down: Optional[float] = None
    count_7d_regime_trend_down: Optional[int] = None
    gross_profit_7d_regime_trend_down: Optional[float] = None
    gross_loss_7d_regime_trend_down: Optional[float] = None
    pf_7d_ex_bootstrap_timeouts: Optional[float] = None
    count_7d_ex_bootstrap_timeouts: Optional[int] = None
    scratch_only_7d_ex_bootstrap_timeouts: Optional[bool] = None
    gross_profit_7d_ex_bootstrap_timeouts: Optional[float] = None
    gross_loss_7d_ex_bootstrap_timeouts: Optional[float] = None
    lossless_7d_ex_bootstrap_timeouts: Optional[bool] = None
    pf_7d_ex_bootstrap: Optional[float] = None
    count_7d_ex_bootstrap: Optional[int] = None
    pf_30d: Optional[float] = None
    count_30d: Optional[int] = None
    scratch_only_30d: Optional[bool] = None
    scratch_count_30d: Optional[int] = None
    lossless_30d: Optional[bool] = None
    gross_profit_30d: Optional[float] = None
    gross_loss_30d: Optional[float] = None
    pf_30d_regime_chop: Optional[float] = None
    count_30d_regime_chop: Optional[int] = None
    gross_profit_30d_regime_chop: Optional[float] = None
    gross_loss_30d_regime_chop: Optional[float] = None
    pf_30d_regime_trend_up: Optional[float] = None
    count_30d_regime_trend_up: Optional[int] = None
    gross_profit_30d_regime_trend_up: Optional[float] = None
    gross_loss_30d_regime_trend_up: Optional[float] = None
    pf_30d_regime_trend_down: Optional[float] = None
    count_30d_regime_trend_down: Optional[int] = None
    gross_profit_30d_regime_trend_down: Optional[float] = None
    gross_loss_30d_regime_trend_down: Optional[float] = None
    pf_30d_ex_bootstrap_timeouts: Optional[float] = None
    count_30d_ex_bootstrap_timeouts: Optional[int] = None
    scratch_only_30d_ex_bootstrap_timeouts: Optional[bool] = None
    gross_profit_30d_ex_bootstrap_timeouts: Optional[float] = None
    gross_loss_30d_ex_bootstrap_timeouts: Optional[float] = None
    lossless_30d_ex_bootstrap_timeouts: Optional[bool] = None
    pf_30d_ex_bootstrap: Optional[float] = None
    count_30d_ex_bootstrap: Optional[int] = None
    phase5j_promotion_candidates: Optional[List[str]] = Field(default_factory=list)


class PositionModel(BaseModel):
    """Individual position model."""
    dir: Optional[int] = None
    bars_open: Optional[int] = None
    entry_px: Optional[float] = None
    entry_ts: Optional[str] = None
    last_ts: Optional[str] = None
    risk_mult: Optional[float] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    trade_kind: Optional[str] = None
    regime: Optional[str] = None
    regime_at_entry: Optional[str] = None


class PositionStateResponse(BaseModel):
    """Position state response."""
    last_updated: Optional[str] = None
    positions: Dict[str, PositionModel] = Field(default_factory=dict)


class SymbolCaps(BaseModel):
    """Symbol trading caps."""
    max_positions: Optional[int] = None
    risk_mult_cap: Optional[float] = None


class SymbolState(BaseModel):
    """Individual symbol state."""
    allow_core: Optional[bool] = None
    allow_exploration: Optional[bool] = None
    allow_recovery: Optional[bool] = None
    sample_stage: Optional[str] = None
    n_closes_7d: Optional[int] = None
    quarantined: Optional[bool] = None
    caps: Optional[SymbolCaps] = None


class SymbolStatesResponse(BaseModel):
    """Symbol states response."""
    symbols: Dict[str, SymbolState] = Field(default_factory=dict)
    generated_at: Optional[str] = None


class TradesRecentResponse(BaseModel):
    """Trades recent response."""
    trades: List[TradeEntry] = Field(default_factory=list)


class PromotionResponse(BaseModel):
    """Promotion response."""
    advice: Optional[Dict[str, Any]] = None
    auto_promotions: Optional[Dict[str, Any]] = None


class ApiStatusResponse(BaseModel):
    """API status response."""
    api_version: str = "1.0.0"
    server_time: str = Field(default_factory=lambda: __import__('datetime').datetime.now().isoformat())
    report_files_status: Dict[str, bool] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    message: str
    timestamp: str = Field(default_factory=lambda: __import__('datetime').datetime.now().isoformat())


# Generic response wrapper
class APIResponse(BaseModel):
    """Generic API response wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: __import__('datetime').datetime.now().isoformat())
