"""
Aurora RAG Chatbot - Multi-Tier Caching Service

Supports in-memory (L1), Redis (L2), and semantic caching.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable
from functools import wraps

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    key: str
    value: Any
    created_at: float
    ttl: float
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """Record access and return value."""
        self.hits += 1
        self.last_accessed = time.time()
        return self.value


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""
    hits: int = 0
    misses: int = 0
    l1_hits: int = 0
    l2_hits: int = 0
    evictions: int = 0
    size: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "l1_hits": self.l1_hits,
            "l2_hits": self.l2_hits,
            "evictions": self.evictions,
            "size": self.size,
            "hit_rate": round(self.hit_rate, 4)
        }


# =============================================================================
# L1 IN-MEMORY CACHE (LRU)
# =============================================================================

class L1Cache:
    """
    In-memory LRU cache for ultra-fast lookups.
    
    Features:
    - O(1) get/set operations
    - LRU eviction policy
    - TTL support
    - Thread-safe with locks
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self.stats = CacheStats()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                return None
            
            if entry.is_expired:
                del self._cache[key]
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self.stats.hits += 1
            self.stats.l1_hits += 1
            
            return entry.access()
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[float] = None
    ) -> None:
        """Set value in cache with optional TTL."""
        async with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self.stats.evictions += 1
            
            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl or self.default_ttl
            )
            self._cache.move_to_end(key)
            self.stats.size = len(self._cache)
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                self.stats.size = len(self._cache)
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._cache.clear()
            self.stats.size = 0
    
    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        async with self._lock:
            expired_keys = [
                k for k, v in self._cache.items() 
                if v.is_expired
            ]
            for key in expired_keys:
                del self._cache[key]
            self.stats.size = len(self._cache)
            return len(expired_keys)


# =============================================================================
# L2 REDIS CACHE
# =============================================================================

class L2Cache:
    """
    Redis-backed cache for persistence and shared state.
    
    Features:
    - Persistent storage
    - Shared across workers
    - Automatic serialization
    - TTL support
    - Graceful degradation when Redis is unavailable
    """
    
    def __init__(self, redis_client, prefix: str = "cache:", default_ttl: int = 300):
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = default_ttl
        self.stats = CacheStats()
        self._healthy = True  # Track health for degraded mode
        self._last_error: str = ""
    
    def _make_key(self, key: str) -> str:
        """Create Redis key with prefix."""
        return f"{self.prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from Redis. Falls back gracefully if Redis is unavailable."""
        if not self.redis:
            return None
        
        try:
            redis_key = self._make_key(key)
            data = await self.redis.get(redis_key)
            
            if data is None:
                self.stats.misses += 1
                return None
            
            self.stats.hits += 1
            self.stats.l2_hits += 1
            
            # Mark as healthy on successful operation
            if not self._healthy:
                logger.info("Redis connection restored - L2 cache back online")
                self._healthy = True
            
            return json.loads(data)
            
        except Exception as e:
            if self._healthy:
                logger.warning(f"Redis unavailable, falling back to L1-only cache: {e}")
                self._healthy = False
                self._last_error = str(e)
            return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in Redis with TTL."""
        if not self.redis:
            return False
        
        try:
            redis_key = self._make_key(key)
            data = json.dumps(value)
            await self.redis.setex(
                redis_key, 
                ttl or self.default_ttl, 
                data
            )
            return True
            
        except Exception as e:
            logger.warning(f"L2 cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        if not self.redis:
            return False
        
        try:
            redis_key = self._make_key(key)
            result = await self.redis.delete(redis_key)
            return result > 0
            
        except Exception as e:
            logger.warning(f"L2 cache delete error: {e}")
            return False
    
    async def clear_prefix(self, pattern: str = "*") -> int:
        """Clear all keys matching pattern."""
        if not self.redis:
            return 0
        
        try:
            keys = []
            async for key in self.redis.scan_iter(f"{self.prefix}{pattern}"):
                keys.append(key)
            
            if keys:
                return await self.redis.delete(*keys)
            return 0
            
        except Exception as e:
            logger.warning(f"L2 cache clear error: {e}")
            return 0


# =============================================================================
# SEMANTIC CACHE
# =============================================================================

class SemanticCache:
    """
    Semantic similarity-based cache for natural language queries.
    
    Finds cached responses for semantically similar queries,
    even if exact wording differs.
    """
    
    def __init__(
        self, 
        embedding_fn: Callable,
        similarity_threshold: float = 0.95,
        max_entries: int = 500
    ):
        self.embedding_fn = embedding_fn
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self._cache: List[Tuple[str, List[float], Any]] = []  # (query, embedding, response)
        self._lock = asyncio.Lock()
        self.stats = CacheStats()
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    async def get(self, query: str) -> Optional[Any]:
        """Find cached response for semantically similar query."""
        try:
            query_embedding = await asyncio.to_thread(
                self.embedding_fn, [query]
            )
            
            if not query_embedding:
                return None
            
            query_vec = query_embedding[0]
            
            async with self._lock:
                best_match = None
                best_score = 0.0
                
                for cached_query, cached_embedding, response in self._cache:
                    score = self._cosine_similarity(query_vec, cached_embedding)
                    if score > best_score and score >= self.similarity_threshold:
                        best_score = score
                        best_match = response
                
                if best_match:
                    self.stats.hits += 1
                    logger.debug(f"Semantic cache hit (score={best_score:.3f})")
                    return best_match
                
                self.stats.misses += 1
                return None
                
        except Exception as e:
            logger.warning(f"Semantic cache error: {e}")
            return None
    
    async def set(self, query: str, response: Any) -> None:
        """Add query-response pair to semantic cache."""
        try:
            query_embedding = await asyncio.to_thread(
                self.embedding_fn, [query]
            )
            
            if not query_embedding:
                return
            
            async with self._lock:
                # Evict oldest if at capacity
                while len(self._cache) >= self.max_entries:
                    self._cache.pop(0)
                    self.stats.evictions += 1
                
                self._cache.append((query, query_embedding[0], response))
                self.stats.size = len(self._cache)
                
        except Exception as e:
            logger.warning(f"Semantic cache set error: {e}")


# =============================================================================
# UNIFIED CACHE SERVICE
# =============================================================================

class CacheService:
    """
    Unified multi-tier caching service.
    
    Lookup order:
    1. L1 (in-memory) - fastest
    2. L2 (Redis) - persistent
    3. Semantic cache - similarity-based (optional)
    
    Write-through: Updates propagate to all tiers.
    """
    
    def __init__(
        self,
        redis_client=None,
        l1_max_size: int = 1000,
        l1_ttl: float = 300.0,
        l2_ttl: int = 600,
        enable_semantic: bool = False,
        embedding_fn: Callable = None,
        semantic_threshold: float = 0.95
    ):
        self.l1 = L1Cache(max_size=l1_max_size, default_ttl=l1_ttl)
        self.l2 = L2Cache(redis_client, default_ttl=l2_ttl) if redis_client else None
        
        self.semantic = None
        if enable_semantic and embedding_fn:
            self.semantic = SemanticCache(
                embedding_fn=embedding_fn,
                similarity_threshold=semantic_threshold
            )
        
        self._cleanup_task = None
    
    @staticmethod
    def generate_key(*args, **kwargs) -> str:
        """Generate cache key from arguments."""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get(
        self, 
        key: str, 
        use_semantic: bool = False,
        query: str = None
    ) -> Tuple[Optional[Any], str]:
        """
        Get value from cache.
        
        Returns:
            Tuple of (value, tier) where tier is "l1", "l2", "semantic", or "miss"
        """
        # Try L1 first
        value = await self.l1.get(key)
        if value is not None:
            return value, "l1"
        
        # Try L2
        if self.l2:
            value = await self.l2.get(key)
            if value is not None:
                # Backfill L1
                await self.l1.set(key, value)
                return value, "l2"
        
        # Try semantic cache
        if use_semantic and self.semantic and query:
            value = await self.semantic.get(query)
            if value is not None:
                # Backfill L1 and L2
                await self.l1.set(key, value)
                if self.l2:
                    await self.l2.set(key, value)
                return value, "semantic"
        
        return None, "miss"
    
    async def set(
        self, 
        key: str, 
        value: Any,
        ttl: Optional[float] = None,
        query: str = None
    ) -> None:
        """Set value in all cache tiers (write-through)."""
        # L1
        await self.l1.set(key, value, ttl)
        
        # L2
        if self.l2:
            await self.l2.set(key, value, int(ttl) if ttl else None)
        
        # Semantic
        if self.semantic and query:
            await self.semantic.set(query, value)
    
    async def delete(self, key: str) -> bool:
        """Delete from all tiers."""
        results = [await self.l1.delete(key)]
        
        if self.l2:
            results.append(await self.l2.delete(key))
        
        return any(results)
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching pattern."""
        count = 0
        
        # L1 - full scan (expensive but necessary)
        async with self.l1._lock:
            keys_to_delete = [
                k for k in self.l1._cache.keys()
                if pattern in k
            ]
            for key in keys_to_delete:
                del self.l1._cache[key]
                count += 1
        
        # L2
        if self.l2:
            count += await self.l2.clear_prefix(pattern)
        
        return count
    
    async def warm(self, items: List[Tuple[str, Any, Optional[float]]]) -> int:
        """
        Warm cache with pre-computed items.
        
        Args:
            items: List of (key, value, ttl) tuples
            
        Returns:
            Number of items warmed
        """
        count = 0
        for key, value, ttl in items:
            await self.set(key, value, ttl)
            count += 1
        
        logger.info(f"Cache warmed with {count} items")
        return count

    async def warm_up_semantic(self, common_qna: List[Tuple[str, str]]) -> int:
        """
        Warm up semantic cache with common Q&A pairs.
        
        This enables instant responses for common queries regardless of 
        user session, as semantic cache key is just the query.
        """
        if not self.semantic:
            return 0
            
        count = 0
        for query, response in common_qna:
            # We construct a response object that matches what get_answer returns
            # This is usually a dict with "answer", "intent", etc.
            response_obj = {
                "answer": response,
                "intent": "warmup", 
                "confidence": 1.0,
                "tier": "High",
                "source": "cache_warmup"
            }
            await self.semantic.set(query, response_obj)
            count += 1
            
        logger.info(f"Semantic cache warmed with {count} common queries")
        return count
    
    def get_stats(self) -> Dict:
        """Get combined statistics from all tiers."""
        stats = {
            "l1": self.l1.stats.to_dict(),
        }
        
        if self.l2:
            stats["l2"] = self.l2.stats.to_dict()
        
        if self.semantic:
            stats["semantic"] = self.semantic.stats.to_dict()
        
        # Calculate totals
        total_hits = self.l1.stats.hits
        total_misses = self.l1.stats.misses
        
        if self.l2:
            total_hits += self.l2.stats.l2_hits
        
        stats["total"] = {
            "hits": total_hits,
            "misses": total_misses,
            "hit_rate": round(total_hits / (total_hits + total_misses), 4) if (total_hits + total_misses) > 0 else 0.0
        }
        
        return stats
    
    async def start_cleanup_task(self, interval: int = 60) -> None:
        """Start background task to clean expired entries."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    removed = await self.l1.cleanup_expired()
                    if removed > 0:
                        logger.debug(f"Cache cleanup: removed {removed} expired entries")
                except Exception as e:
                    logger.error(f"Cache cleanup error: {e}")
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def stop_cleanup_task(self) -> None:
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass


# =============================================================================
# CACHE DECORATOR
# =============================================================================

def cached(
    ttl: float = 300.0,
    key_prefix: str = "",
    use_semantic: bool = False
):
    """
    Decorator to cache function results.
    
    Usage:
        @cached(ttl=300, key_prefix="user")
        async def get_user_data(user_id: str):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, cache_service: CacheService = None, **kwargs):
            if not cache_service:
                # No cache service provided, run function directly
                return await func(*args, **kwargs)
            
            # Generate cache key
            key = f"{key_prefix}:{CacheService.generate_key(*args, **kwargs)}"
            
            # Try cache
            value, tier = await cache_service.get(key)
            if value is not None:
                return value
            
            # Cache miss - run function
            result = await func(*args, **kwargs)
            
            # Store result
            await cache_service.set(key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_cache_service: Optional[CacheService] = None


def get_cache_service() -> Optional[CacheService]:
    """Get the global cache service instance."""
    return _cache_service


async def init_cache_service(
    redis_client=None,
    **kwargs
) -> CacheService:
    """Initialize the global cache service."""
    global _cache_service
    
    _cache_service = CacheService(
        redis_client=redis_client,
        **kwargs
    )
    
    await _cache_service.start_cleanup_task()
    logger.info("Cache service initialized")
    
    return _cache_service
