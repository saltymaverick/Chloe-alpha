"""
Chloe Alpha Read-Only API
FastAPI service for dashboard data access.
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import os

from .auth import require_auth, check_rate_limit
from .readers import (
    get_health_status, get_status_data, get_pf_data, get_positions, get_symbol_states,
    get_promotion_data, get_recent_trades, get_meta_log_sizes
)
from .models import (
    HealthResponse, MetaLogSizesResponse, TradeEntry,
    PfResponse, PositionStateResponse, SymbolStatesResponse,
    TradesRecentResponse, PromotionResponse, ApiStatusResponse,
    ErrorResponse, APIResponse
)

# Create FastAPI app
app = FastAPI(
    title="Chloe Alpha API",
    description="Read-only API for Chloe Alpha dashboard data",
    version="1.0.0",
    docs_url="/docs",  # OpenAPI docs
    redoc_url="/redoc"
)

# CORS middleware (restrict to your dashboard domains in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict to your dashboard domain
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "Chloe Alpha API",
        "version": "1.0.0",
        "description": "Read-only dashboard data API",
        "docs": "/docs"
    }


@app.get("/status", response_model=ApiStatusResponse)
async def get_api_status(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get API status and report file availability."""
    # Check key report files
    report_files = {
        "loop_health.json": "reports/loop_health.json",
        "pf_local.json": "reports/pf_local.json",
        "position_state.json": "reports/position_state.json",
        "symbol_states.json": "reports/risk/symbol_states.json",
        "trades.jsonl": "reports/trades.jsonl",
        "promotion_advice.json": "reports/gpt/promotion_advice.json",
        "auto_promotions.json": "reports/risk/auto_promotions.json",
    }

    files_status = {}
    for name, path in report_files.items():
        from pathlib import Path
        full_path = Path(__file__).parent.parent.parent / path
        files_status[name] = full_path.exists()

    return ApiStatusResponse(report_files_status=files_status)


@app.get("/health", response_model=HealthResponse)
async def get_health(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get Chloe loop health status."""
    data, error = get_health_status()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return HealthResponse(**data)


@app.get("/status")
async def get_status(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get Chloe system status."""
    data, error = get_status_data()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return APIResponse(success=True, data=data)


@app.get("/pf", response_model=PfResponse)
async def get_pf(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get current PF (Profit Factor) data."""
    data, error = get_pf_data()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return PfResponse(**data)


@app.get("/positions", response_model=PositionStateResponse)
async def get_position_data(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get current position states."""
    data, error = get_positions()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return PositionStateResponse(**data)


@app.get("/symbols")
async def get_symbols_data(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get symbol trading states."""
    data, error = get_symbol_states()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return APIResponse(success=True, data=data)


@app.get("/symbols/states", response_model=SymbolStatesResponse)
async def get_symbols_states_data(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get symbol trading states."""
    data, error = get_symbol_states()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return SymbolStatesResponse(**data)


@app.get("/promotion", response_model=PromotionResponse)
async def get_promotion_data_endpoint(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get promotion advice and auto promotions."""
    data, error = get_promotion_data()
    if error:
        raise HTTPException(status_code=404, detail=error)

    return PromotionResponse(**data)


@app.get("/trades/recent", response_model=TradesRecentResponse)
async def get_recent_trades_data(
    hours: int = 6,
    limit: int = 200,
    request: Request = require_auth,
    rate_limit: Request = check_rate_limit
):
    """Get recent trades from the last N hours."""
    if hours < 1 or hours > 168:  # Max 1 week
        raise HTTPException(status_code=400, detail="hours must be between 1 and 168")
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")

    data, error = get_recent_trades(hours, limit)
    if error:
        raise HTTPException(status_code=404, detail=error)

    return TradesRecentResponse(trades=data)


@app.get("/meta/log_sizes", response_model=MetaLogSizesResponse)
async def get_meta_log_sizes_data(request: Request = require_auth, rate_limit: Request = check_rate_limit):
    """Get sizes and metadata for key log files."""
    data = get_meta_log_sizes()
    return MetaLogSizesResponse(**data)


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Handle 404 errors with consistent format."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error="NOT_FOUND",
            message=exc.detail
        ).dict()
    )


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: HTTPException):
    """Handle auth errors."""
    return JSONResponse(
        status_code=401,
        content=ErrorResponse(
            error="UNAUTHORIZED",
            message=exc.detail
        ).dict()
    )


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc: HTTPException):
    """Handle rate limit errors."""
    return JSONResponse(
        status_code=429,
        content=ErrorResponse(
            error="RATE_LIMITED",
            message=exc.detail
        ).dict()
    )


if __name__ == "__main__":
    # For development/testing
    port = int(os.getenv("CHLOE_API_PORT", "8001"))
    host = os.getenv("CHLOE_API_HOST", "0.0.0.0")

    uvicorn.run(
        "engine_alpha.api.app:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
