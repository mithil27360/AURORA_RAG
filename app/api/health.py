"""
Aurora RAG Chatbot - Health Check Service

Component health verification with Kubernetes-compatible probes.
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


# =============================================================================
# HEALTH STATUS
# =============================================================================

class HealthStatus(str, Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    last_check: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
            "details": self.details,
            "last_check": self.last_check
        }


@dataclass
class OverallHealth:
    """Overall system health status."""
    status: HealthStatus
    components: List[ComponentHealth]
    timestamp: float = field(default_factory=time.time)
    version: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "version": self.version,
            "timestamp": self.timestamp,
            "components": {c.name: c.to_dict() for c in self.components}
        }


# =============================================================================
# HEALTH CHECK REGISTRY
# =============================================================================

class HealthCheckRegistry:
    """Registry for health check functions."""
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._critical: set = set()  # Components that affect overall health
        self._last_results: Dict[str, ComponentHealth] = {}
        self._cache_ttl: float = 5.0  # Cache results for 5 seconds
    
    def register(
        self, 
        name: str, 
        check_fn: Callable,
        critical: bool = True
    ) -> None:
        """
        Register a health check function.
        
        Args:
            name: Component name
            check_fn: Async function returning ComponentHealth
            critical: If True, failure affects overall health
        """
        self._checks[name] = check_fn
        if critical:
            self._critical.add(name)
    
    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        self._checks.pop(name, None)
        self._critical.discard(name)
    
    async def check_component(self, name: str) -> ComponentHealth:
        """Run health check for a single component."""
        if name not in self._checks:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNKNOWN,
                message="Component not registered"
            )
        
        # Check cache
        cached = self._last_results.get(name)
        if cached and (time.time() - cached.last_check) < self._cache_ttl:
            return cached
        
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._checks[name](),
                timeout=10.0
            )
            result.latency_ms = (time.perf_counter() - start) * 1000
            self._last_results[name] = result
            return result
            
        except asyncio.TimeoutError:
            result = ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="Health check timed out"
            )
            self._last_results[name] = result
            return result
            
        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            result = ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=str(e)
            )
            self._last_results[name] = result
            return result
    
    async def check_all(self, version: str = "") -> OverallHealth:
        """Run all health checks and determine overall status."""
        tasks = [
            self.check_component(name)
            for name in self._checks
        ]
        
        components = await asyncio.gather(*tasks)
        
        # Determine overall status
        critical_statuses = [
            c.status for c in components 
            if c.name in self._critical
        ]
        
        if not critical_statuses:
            overall = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in critical_statuses):
            overall = HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in critical_statuses):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY
        
        return OverallHealth(
            status=overall,
            components=components,
            version=version
        )
    
    def is_ready(self) -> bool:
        """Quick check if system is ready (for K8s readiness probe)."""
        for name in self._critical:
            cached = self._last_results.get(name)
            if not cached or cached.status == HealthStatus.UNHEALTHY:
                return False
        return True
    
    def is_alive(self) -> bool:
        """Quick check if system is alive (for K8s liveness probe)."""
        # Basic liveness - just check if the process is responding
        return True


# =============================================================================
# BUILT-IN HEALTH CHECKS
# =============================================================================

async def check_redis(redis_client) -> ComponentHealth:
    """Check Redis connectivity."""
    try:
        if not redis_client:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.DEGRADED,
                message="Redis client not configured (using in-memory fallback)"
            )
        
        start = time.perf_counter()
        await redis_client.ping()
        latency = (time.perf_counter() - start) * 1000
        
        # Get info
        info = await redis_client.info("memory")
        
        return ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=latency,
            details={
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0)
            }
        )
        
    except Exception as e:
        return ComponentHealth(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            message=str(e)
        )


async def check_vector_store(vector_service) -> ComponentHealth:
    """Check vector store (ChromaDB) health."""
    try:
        if not vector_service or not vector_service.collection:
            return ComponentHealth(
                name="vector_store",
                status=HealthStatus.UNHEALTHY,
                message="Vector store not initialized"
            )
        
        start = time.perf_counter()
        # Run a simple query to verify connectivity
        count = vector_service.collection.count()
        latency = (time.perf_counter() - start) * 1000
        
        return ComponentHealth(
            name="vector_store",
            status=HealthStatus.HEALTHY,
            latency_ms=latency,
            details={
                "document_count": count,
                "collection_name": vector_service.collection.name
            }
        )
        
    except Exception as e:
        return ComponentHealth(
            name="vector_store",
            status=HealthStatus.UNHEALTHY,
            message=str(e)
        )


async def check_llm_service(llm_service) -> ComponentHealth:
    """Check LLM service health."""
    try:
        if not llm_service or not llm_service.client:
            return ComponentHealth(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message="LLM client not initialized"
            )
        
        # Just verify the client is configured
        # Don't make actual API calls in health check (save tokens)
        stats = llm_service.get_usage_stats()
        
        return ComponentHealth(
            name="llm",
            status=HealthStatus.HEALTHY,
            details={
                "model": getattr(llm_service, 'model', 'unknown'),
                "usage_stats": stats
            }
        )
        
    except Exception as e:
        return ComponentHealth(
            name="llm",
            status=HealthStatus.DEGRADED,
            message=str(e)
        )


async def check_database(db_path) -> ComponentHealth:
    """Check SQLite database health."""
    try:
        import aiosqlite
        from pathlib import Path
        
        if not Path(db_path).exists():
            return ComponentHealth(
                name="database",
                status=HealthStatus.DEGRADED,
                message="Database file does not exist (will be created on first write)"
            )
        
        start = time.perf_counter()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM sqlite_master")
            table_count = (await cursor.fetchone())[0]
        
        latency = (time.perf_counter() - start) * 1000
        
        return ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            latency_ms=latency,
            details={
                "tables": table_count,
                "path": str(db_path)
            }
        )
        
    except Exception as e:
        return ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=str(e)
        )


async def check_external_api(
    name: str,
    url: str,
    timeout: float = 5.0
) -> ComponentHealth:
    """Check external API health via HTTP GET."""
    try:
        import aiohttp
        
        start = time.perf_counter()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as response:
                latency = (time.perf_counter() - start) * 1000
                
                if response.status == 200:
                    return ComponentHealth(
                        name=name,
                        status=HealthStatus.HEALTHY,
                        latency_ms=latency,
                        details={"status_code": response.status}
                    )
                else:
                    return ComponentHealth(
                        name=name,
                        status=HealthStatus.DEGRADED,
                        latency_ms=latency,
                        message=f"Unexpected status: {response.status}"
                    )
                    
    except Exception as e:
        return ComponentHealth(
            name=name,
            status=HealthStatus.UNHEALTHY,
            message=str(e)
        )


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_health_registry = HealthCheckRegistry()


def get_health_registry() -> HealthCheckRegistry:
    """Get the global health check registry."""
    return _health_registry


# =============================================================================
# FASTAPI INTEGRATION
# =============================================================================

def create_health_endpoints(app, version: str = ""):
    """
    Create FastAPI health check endpoints.
    
    Adds:
    - /health - Full health check
    - /health/live - Liveness probe (K8s)
    - /health/ready - Readiness probe (K8s)
    """
    from fastapi import Response
    from fastapi.responses import JSONResponse
    
    @app.get("/health")
    async def health_check():
        """Full health check with component details."""
        result = await _health_registry.check_all(version=version)
        
        status_code = 200 if result.status == HealthStatus.HEALTHY else (
            503 if result.status == HealthStatus.UNHEALTHY else 200
        )
        
        return JSONResponse(
            content=result.to_dict(),
            status_code=status_code
        )
    
    @app.get("/health/live")
    async def liveness_probe():
        """Kubernetes liveness probe."""
        if _health_registry.is_alive():
            return {"status": "alive"}
        return Response(status_code=503)
    
    @app.get("/health/ready")
    async def readiness_probe():
        """Kubernetes readiness probe."""
        if _health_registry.is_ready():
            return {"status": "ready"}
        return Response(status_code=503)


# =============================================================================
# CIRCUIT BREAKER INTEGRATION
# =============================================================================

class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failure threshold exceeded, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """
    
    class State(Enum):
        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half_open"
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self._state = self.State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> State:
        return self._state
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self._state == self.State.OPEN:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = self.State.HALF_OPEN
                    self._success_count = 0
                    logger.info(f"Circuit breaker {self.name}: OPEN -> HALF_OPEN")
                else:
                    raise CircuitBreakerOpen(f"Circuit breaker {self.name} is open")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Handle successful call."""
        async with self._lock:
            if self._state == self.State.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = self.State.CLOSED
                    self._failure_count = 0
                    logger.info(f"Circuit breaker {self.name}: HALF_OPEN -> CLOSED")
            else:
                self._failure_count = 0
    
    async def _on_failure(self):
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == self.State.HALF_OPEN:
                self._state = self.State.OPEN
                logger.warning(f"Circuit breaker {self.name}: HALF_OPEN -> OPEN")
            elif self._failure_count >= self.failure_threshold:
                self._state = self.State.OPEN
                logger.warning(f"Circuit breaker {self.name}: CLOSED -> OPEN")


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


def with_circuit_breaker(breaker: CircuitBreaker):
    """Decorator to apply circuit breaker to a function."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
