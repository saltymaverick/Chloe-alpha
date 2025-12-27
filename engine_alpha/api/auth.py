"""
Chloe Alpha API Authentication
Token-based authentication for read-only dashboard endpoints.
"""
import os
from typing import Optional
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


class ChloeAPIAuth:
    """API key authentication for Chloe API endpoints."""

    def __init__(self):
        # Get API key from environment (disabled if not set)
        self.expected_key = os.getenv("CHLOE_API_KEY")
        self.enabled = self.expected_key is not None

    def authenticate(self, request: Request) -> bool:
        """Check if request has valid API key. Returns True if auth passes."""
        if not self.enabled:
            return True  # Auth disabled if no key set

        # Check X-CHLOE-API-KEY header
        api_key = request.headers.get("X-CHLOE-API-KEY")
        if not api_key:
            return False

        return api_key == self.expected_key


# Global auth instance
auth = ChloeAPIAuth()


def require_auth(request: Request) -> Request:
    """FastAPI dependency for authentication."""
    if not auth.authenticate(request):
        if auth.enabled:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key. Use X-CHLOE-API-KEY header."
            )
        else:
            raise HTTPException(
                status_code=503,
                detail="API authentication not configured. Set CHLOE_API_KEY environment variable."
            )

    return request


# Rate limiting (simple in-memory)
from collections import defaultdict, deque
import time

class SimpleRateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(lambda: deque())

    def is_allowed(self, client_ip: str) -> bool:
        """Check if request is allowed for this client."""
        now = time.time()
        client_requests = self.requests[client_ip]

        # Remove old requests outside the window
        while client_requests and client_requests[0] < now - self.window_seconds:
            client_requests.popleft()

        # Check if under limit
        if len(client_requests) >= self.max_requests:
            return False

        # Add this request
        client_requests.append(now)
        return True


rate_limiter = SimpleRateLimiter()


def check_rate_limit(request: Request) -> Request:
    """FastAPI dependency for rate limiting."""
    client_ip = request.client.host if request.client else "unknown"

    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later."
        )

    return request
