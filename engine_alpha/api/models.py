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
