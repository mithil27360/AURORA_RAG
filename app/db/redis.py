import redis.asyncio as redis
import json
import logging
import hashlib
from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy-load embedding model (same as vector service)
_embedder = None
def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder

def compute_similarity(emb1, emb2):
    """Compute cosine similarity between two embeddings."""
    import numpy as np
    a = np.array(emb1)
    b = np.array(emb2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

class InMemoryRedis:
    """Fallback for when Redis is not available (Dev Mode)"""
    def __init__(self):
        self.store = {}
        self.semantic_cache = []  # List of {query, embedding, response}
        logger.warning("Redis not available. Using In-Memory fallback (Data will be lost on restart).")

    async def get(self, key: str):
        return self.store.get(key)
    
    async def set(self, key: str, value: str, ex: int = None):
        self.store[key] = value

class RedisClient:
    def __init__(self):
        self.semantic_cache = []  # In-memory semantic cache
        self.SIMILARITY_THRESHOLD = 0.85  # Match if >85% similar
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
        history = history[-5:]
        
        await self.redis.set(
            f"history:{user_id}", 
            json.dumps(history),
            ex=3600*24
        )
    
    async def get_cache(self, key: str):
        """Get cached response (exact match)"""
        await self._ensure_connection()
        data = await self.redis.get(f"cache:{key}")
        return json.loads(data) if data else None

    async def get_semantic_cache(self, query: str):
        """Find cached response for semantically similar queries."""
        if not self.semantic_cache:
            return None
        
        try:
            embedder = get_embedder()
            query_emb = embedder.encode(query.lower().strip())
            
            best_match = None
            best_score = 0
            
            for entry in self.semantic_cache[-100:]:  # Check last 100 entries
                score = compute_similarity(query_emb, entry["embedding"])
                if score > best_score and score >= self.SIMILARITY_THRESHOLD:
                    best_score = score
                    best_match = entry
            
            if best_match:
                logger.info(f"Semantic cache HIT: '{query}' matched '{best_match['query']}' ({best_score:.0%} similar)")
                return best_match["response"]
            return None
        except Exception as e:
            logger.warning(f"Semantic cache lookup failed: {e}")
            return None

    async def set_cache(self, key: str, value: dict, ttl: int = None, query: str = None):
        """Set cached response (with semantic indexing)"""
        if ttl is None:
            ttl = settings.cache.ttl_seconds if hasattr(settings, 'cache') else 3600
        await self._ensure_connection()
        await self.redis.set(
            f"cache:{key}",
            json.dumps(value),
            ex=ttl
        )
        
        # Also add to semantic cache if query provided
        if query:
            try:
                embedder = get_embedder()
                embedding = embedder.encode(query.lower().strip()).tolist()
                self.semantic_cache.append({
                    "query": query,
                    "embedding": embedding,
                    "response": value
                })
                # Keep only last 500 entries
                if len(self.semantic_cache) > 500:
                    self.semantic_cache = self.semantic_cache[-500:]
            except Exception as e:
                logger.warning(f"Failed to index query for semantic cache: {e}")

# Global instance
redis_client = None

async def init_redis():
    global redis_client
    redis_client = RedisClient()
    await redis_client._ensure_connection()

async def get_redis():
    return redis_client
