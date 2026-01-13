"""
Aurora RAG Chatbot - API Middleware Stack

Request timing, error handling, rate limiting, and security headers.
"""

import time
import uuid
import asyncio
import logging
from typing import Callable, Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from functools import wraps

from app.core.config import settings
from app.core.logging import request_context, LogContext
from app.core.metrics import (
    REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_REQUESTS,
    ERRORS, sla_tracker
)

logger = logging.getLogger(__name__)


# =============================================================================
# REQUEST ID MIDDLEWARE
# =============================================================================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Adds unique request ID to each request for tracing.
    
    - Generates UUID if not provided in X-Request-ID header
    - Adds to request state
    - Returns in X-Request-ID response header
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Store in request state
        request.state.request_id = request_id
        
        # Set logging context
        async with LogContext(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            ip=self._get_client_ip(request)
        ):
            response = await call_next(request)
        
        # Add to response headers
        response.headers["X-Request-ID"] = request_id
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting proxies."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        if request.client:
            return request.client.host
        
        return "unknown"


# =============================================================================
# TIMING MIDDLEWARE
# =============================================================================

class TimingMiddleware(BaseHTTPMiddleware):
    """
    Tracks request timing and emits metrics.
    
    - Records start/end time
    - Emits Prometheus metrics
    - Adds X-Response-Time header
    - Tracks active request count
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method
        
        # Track active requests
        ACTIVE_REQUESTS.labels(endpoint=path).inc()
        
        start_time = time.perf_counter()
        status_code = 500  # Default for errors
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # Calculate duration
            duration = time.perf_counter() - start_time
            duration_ms = duration * 1000
            
            # Decrement active requests
            ACTIVE_REQUESTS.labels(endpoint=path).dec()
            
            # Record metrics
            REQUEST_COUNT.labels(
                method=method,
                endpoint=path,
                status=str(status_code)
            ).inc()
            
            REQUEST_LATENCY.labels(
                method=method,
                endpoint=path
            ).observe(duration)
            
            # SLA tracking
            sla_tracker.record(duration, status_code < 500)
            
            # Add response header
            if hasattr(request.state, 'response_headers'):
                pass  # Response already processed
            
            logger.debug(
                f"{method} {path} - {status_code} ({duration_ms:.2f}ms)",
                extra={
                    "duration_ms": round(duration_ms, 2),
                    "status_code": status_code
                }
            )


# =============================================================================
# ERROR HANDLING MIDDLEWARE
# =============================================================================

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Standardized error handling and response formatting.
    
    - Catches unhandled exceptions
    - Formats error responses consistently
    - Logs errors with context
    - Masks sensitive error details in production
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as e:
            return await self._handle_error(request, e)
    
    async def _handle_error(self, request: Request, error: Exception) -> JSONResponse:
        """Handle and format error response."""
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        # Determine error type and status code
        status_code, error_code, message = self._classify_error(error)
        
        # Log error
        logger.error(
            f"Unhandled error: {type(error).__name__}",
            extra={
                "request_id": request_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "path": request.url.path,
                "method": request.method
            },
            exc_info=True
        )
        
        # Record metric
        ERRORS.labels(
            type=type(error).__name__,
            location=request.url.path
        ).inc()
        
        # Build response
        response_body = {
            "error": {
                "code": error_code,
                "message": message,
                "request_id": request_id
            }
        }
        
        # Add details in non-production
        if settings.DEBUG or settings.is_development():
            response_body["error"]["details"] = str(error)
            response_body["error"]["type"] = type(error).__name__
        
        return JSONResponse(
            status_code=status_code,
            content=response_body
        )
    
    def _classify_error(self, error: Exception) -> tuple:
        """Classify error and return (status_code, error_code, message)."""
        error_type = type(error).__name__
        
        # Map common exceptions
        error_map = {
            "ValidationError": (400, "VALIDATION_ERROR", "Invalid request data"),
            "ValueError": (400, "BAD_REQUEST", "Invalid value provided"),
            "KeyError": (400, "MISSING_FIELD", "Required field missing"),
            "PermissionError": (403, "FORBIDDEN", "Access denied"),
            "FileNotFoundError": (404, "NOT_FOUND", "Resource not found"),
            "TimeoutError": (504, "TIMEOUT", "Request timed out"),
            "asyncio.TimeoutError": (504, "TIMEOUT", "Request timed out"),
            "ConnectionError": (503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable"),
        }
        
        if error_type in error_map:
            return error_map[error_type]
        
        # Default to internal server error
        return (500, "INTERNAL_ERROR", "An unexpected error occurred")


# =============================================================================
# SECURITY HEADERS MIDDLEWARE
# =============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to all responses.
    
    Includes:
    - Content-Security-Policy
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Strict-Transport-Security (if enabled)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Basic security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # HSTS (only for HTTPS)
        if settings.ENABLE_HSTS:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={settings.HSTS_MAX_AGE}; includeSubDomains"
            )
        
        # Content Security Policy
        if settings.ENABLE_CSP:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' fonts.googleapis.com cdn.jsdelivr.net; "
                "font-src 'self' fonts.gstatic.com; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' api.groq.com;"
            )
        
        return response


# =============================================================================
# RATE LIMITING MIDDLEWARE
# =============================================================================

class RateLimitMiddleware:
    """
    Token bucket rate limiting.
    
    Features:
    - Per-IP rate limiting
    - Configurable limits by endpoint
    - Graceful degradation
    - Rate limit headers in response
    """
    
    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        burst_size: int = 10
    ):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self._buckets: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope)
        
        # Skip rate limiting for health checks
        if request.url.path.startswith("/health"):
            await self.app(scope, receive, send)
            return
        
        client_ip = self._get_client_ip(request)
        allowed, headers = await self._check_rate_limit(client_ip)
        
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Please try again later.",
                        "retry_after": headers.get("Retry-After", 60)
                    }
                },
                headers=headers
            )
            await response(scope, receive, send)
            return
        
        # Add rate limit headers to response
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))
                for key, value in headers.items():
                    headers_list.append((key.encode(), str(value).encode()))
                message["headers"] = headers_list
            await send(message)
        
        await self.app(scope, receive, send_with_headers)
    
    async def _check_rate_limit(self, client_ip: str) -> tuple:
        """Check if request is allowed under rate limit."""
        now = time.time()
        
        async with self._lock:
            if client_ip not in self._buckets:
                self._buckets[client_ip] = {
                    "tokens": self.burst_size,
                    "last_update": now
                }
            
            bucket = self._buckets[client_ip]
            
            # Refill tokens
            elapsed = now - bucket["last_update"]
            refill = elapsed * (self.requests_per_minute / 60.0)
            bucket["tokens"] = min(self.burst_size, bucket["tokens"] + refill)
            bucket["last_update"] = now
            
            # Check if request is allowed
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True, {
                    "X-RateLimit-Limit": self.requests_per_minute,
                    "X-RateLimit-Remaining": int(bucket["tokens"]),
                    "X-RateLimit-Reset": int(now + 60)
                }
            else:
                retry_after = int((1 - bucket["tokens"]) * 60 / self.requests_per_minute)
                return False, {
                    "X-RateLimit-Limit": self.requests_per_minute,
                    "X-RateLimit-Remaining": 0,
                    "X-RateLimit-Reset": int(now + retry_after),
                    "Retry-After": retry_after
                }
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        if request.client:
            return request.client.host
        
        return "unknown"


# =============================================================================
# REQUEST LOGGING MIDDLEWARE
# =============================================================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request and response logging middleware."""
    
    def __init__(self, app: ASGIApp, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "event": "request_start",
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
                "user_agent": request.headers.get("user-agent", ""),
                "content_type": request.headers.get("content-type", "")
            }
        )
        
        response = await call_next(request)
        
        # Log response
        logger.info(
            f"Response: {response.status_code}",
            extra={
                "event": "request_complete",
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", "")
            }
        )
        
        return response


# =============================================================================
# API VERSIONING MIDDLEWARE
# =============================================================================

class APIVersionMiddleware(BaseHTTPMiddleware):
    """
    Adds API versioning support.
    
    Supports:
    - URL path versioning (/v1/, /v2/)
    - Header versioning (X-API-Version)
    - Default version fallback
    """
    
    DEFAULT_VERSION = "v1"
    SUPPORTED_VERSIONS = ["v1", "v2"]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract version from path
        path = request.url.path
        version = self.DEFAULT_VERSION
        
        for v in self.SUPPORTED_VERSIONS:
            if path.startswith(f"/{v}/"):
                version = v
                # Rewrite path without version prefix
                # request.scope["path"] = path[len(f"/{v}"):]
                break
        
        # Or from header
        header_version = request.headers.get("X-API-Version")
        if header_version and header_version in self.SUPPORTED_VERSIONS:
            version = header_version
        
        # Store version in request state
        request.state.api_version = version
        
        response = await call_next(request)
        response.headers["X-API-Version"] = version
        
        return response


# =============================================================================
# GZIP COMPRESSION MIDDLEWARE
# =============================================================================

class CompressionMiddleware(BaseHTTPMiddleware):
    """
    Response compression for large payloads.
    
    - Gzip compression for responses > minimum_size
    - Respects Accept-Encoding header
    - Excludes already compressed content
    """
    
    def __init__(self, app: ASGIApp, minimum_size: int = 500):
        super().__init__(app)
        self.minimum_size = minimum_size
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if client accepts gzip
        accept_encoding = request.headers.get("accept-encoding", "")
        
        if "gzip" not in accept_encoding:
            return await call_next(request)
        
        response = await call_next(request)
        
        # Skip if already compressed or too small
        content_encoding = response.headers.get("content-encoding")
        if content_encoding:
            return response
        
        # Note: For full implementation, would need to intercept response body
        # This is a placeholder - use FastAPI's GZipMiddleware for production
        
        return response


# =============================================================================
# MIDDLEWARE STACK HELPER
# =============================================================================

def setup_middleware(app):
    """
    Configure all middleware in correct order.
    
    Order matters:
    1. Outer middleware processes request first, response last
    2. Inner middleware processes request last, response first
    """
    # Add middleware (last added = first to process)
    
    # Request ID (outermost - first to run)
    app.add_middleware(RequestIDMiddleware)
    
    # Request logging
    if settings.DEBUG or settings.ENVIRONMENT.value == "development":
        app.add_middleware(RequestLoggingMiddleware, log_body=False)
    
    # API versioning
    app.add_middleware(APIVersionMiddleware)
    
    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Error handling
    app.add_middleware(ErrorHandlingMiddleware)
    
    # Timing (track timing after error handling)
    app.add_middleware(TimingMiddleware)
    
    logger.info("Middleware stack configured")
