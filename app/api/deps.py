
from fastapi import Request
from app.db.redis import get_redis, RedisClient
from app.db.sqlite import get_logger, InteractionLogger
from app.services.vector import get_vector_service, VectorService
from app.services.llm import get_llm_service, LLMService
from app.services.security import get_security, SecurityService

async def get_db_redis() -> RedisClient:
    return await get_redis()

def get_interaction_logger() -> InteractionLogger:
    return get_logger()

def get_vector_store() -> VectorService:
    return get_vector_service()

def get_llm() -> LLMService:
    return get_llm_service()

def get_security_service() -> SecurityService:
    return get_security()
