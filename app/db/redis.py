import redis.asyncio as redis
import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class InMemoryRedis:
    """Fallback for when Redis is not available (Dev Mode)"""
    def __init__(self):
        self.store = {}
        logger.warning("Redis not available. Using In-Memory fallback (Data will be lost on restart).")

    async def get(self, key: str):
        return self.store.get(key)
    
    async def set(self, key: str, value: str, ex: int = None):
        self.store[key] = value

class RedisClient:
    def __init__(self):
        try:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2.0)
            self.use_redis = True
        except Exception:
            self.use_redis = False
            self.redis = InMemoryRedis()

    async def _ensure_connection(self):
        if self.use_redis:
            try:
                await self.redis.ping()
            except Exception:
                logger.error("Redis connection failed. Switching to In-Memory fallback.")
                self.redis = InMemoryRedis()
                self.use_redis = False

    async def get_history(self, user_id: str):
        """Get conversation history for a user"""
        await self._ensure_connection()
        key = f"history:{user_id}"
        data = await self.redis.get(key)
        return json.loads(data) if data else []

    async def add_history(self, user_id: str, query: str, answer: str):
        """Add interaction to history with cap"""
        await self._ensure_connection()
        history = await self.get_history(user_id)
        history.append({"query": query, "answer": answer})
        # Retain only the 5 most recent interactions
        history = history[-5:]
        
        await self.redis.set(
            f"history:{user_id}", 
            json.dumps(history),
            ex=3600*24 # 24 hour TTL
        )
    
    async def get_cache(self, key: str):
        """Get cached response"""
        await self._ensure_connection()
        data = await self.redis.get(f"cache:{key}")
        return json.loads(data) if data else None

    async def set_cache(self, key: str, value: dict, ttl: int = settings.CACHE_TTL_SECONDS):
        """Set cached response"""
        await self._ensure_connection()
        await self.redis.set(
            f"cache:{key}",
            json.dumps(value),
            ex=ttl
        )

# Global instance (initialized in main startup)
redis_client = None

async def init_redis():
    global redis_client
    redis_client = RedisClient()
    # Eager connection check
    await redis_client._ensure_connection()

async def get_redis():
    return redis_client
