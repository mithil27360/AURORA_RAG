"""Aurora Fest RAG Chatbot - Main Application Entry Point."""

import logging
import asyncio
import secrets

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.routes import router as api_router
from app.db.redis import init_redis
from app.services.sheets import get_sheets_service
from app.services.vector import get_vector_service

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    logger.info("Starting Aurora Fest RAG Chatbot v2.0")
    
    await init_redis()
    
    sheets = get_sheets_service()
    vector = get_vector_service()
    
    # Initialize Cache Service with Semantic Capabilities
    from app.services.cache import init_cache_service
    from app.db.redis import get_redis
    from app.core.constants import COMMON_QNA
    
    redis_client = await get_redis()
    # Note: Pass vector.embedding directly if it's callable, otherwise wrap it
    cache_service = await init_cache_service(
        redis_client=redis_client.redis if hasattr(redis_client, 'redis') else None,
        embedding_fn=vector.embedding,
        enable_semantic=True,
        semantic_threshold=settings.SEMANTIC_CACHE_THRESHOLD
    )
    
    # Warm up cache for instant responses
    await cache_service.warm_up_semantic(COMMON_QNA)
    
    # Only schedule sync on primary worker using Redis distributed lock
    # This ensures exactly one worker handles scheduled syncs across all processes
    import os
    worker_pid = os.getpid()
    
    if settings.AUTO_SYNC_ENABLED:
        try:
            # Try to acquire distributed lock in Redis (expires after 10 minutes)
            lock_key = "sync_scheduler_lock"
            lock_acquired = await redis_client.set(
                lock_key,
                str(worker_pid),
                ex=600,  # 10 minutes expiry (2x sync interval for safety)
                nx=True  # Only set if not exists
            )
            
            if lock_acquired:
                asyncio.create_task(_initial_sync(sheets, vector))
                asyncio.create_task(_periodic_sync_scheduler(sheets, vector, redis_client, lock_key))
                logger.info(f"Auto-sync ENABLED on primary worker (PID {worker_pid}): interval={settings.SYNC_INTERVAL_MINUTES}m")
            else:
                # Another worker holds the lock
                lock_holder = await redis_client.get(lock_key)
                logger.info(f"Auto-sync DISABLED on secondary worker (PID {worker_pid}). Primary is PID {lock_holder}")
        except Exception as e:
            # Fallback: if Redis fails, proceed (better to have duplicate syncs than none)
            logger.warning(f"Redis lock failed, proceeding with sync anyway: {e}")
            asyncio.create_task(_initial_sync(sheets, vector))
            asyncio.create_task(_periodic_sync_scheduler(sheets, vector, redis_client, lock_key))

    yield
    
    logger.info("Shutting down...")


# Instrumentator for Prometheus
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[".*admin.*", "/metrics"],
    env_var_name="ENABLE_METRICS",
    inprogress_name="inprogress",
    inprogress_labels=True,
)


async def _initial_sync(sheets, vector):
    """Perform initial data sync from Google Sheets."""
    logger.info("Starting initial sync...")
    try:
        events = await asyncio.wait_for(
            asyncio.to_thread(sheets.fetch_events),
            timeout=settings.SYNC_TIMEOUT_SECONDS
        )
        await vector.update_kb(events)
        logger.info("Initial sync complete")
    except asyncio.TimeoutError:
        logger.error(f"Initial sync timeout ({settings.SYNC_TIMEOUT_SECONDS}s)")
    except Exception as e:
        logger.error(f"Initial sync failed: {e}")


async def _periodic_sync_scheduler(sheets, vector, redis_client=None, lock_key=None):
    """Background scheduler for periodic data refresh with distributed lock renewal."""
    import os
    worker_pid = os.getpid()
    while True:
        try:
            await asyncio.sleep(settings.SYNC_INTERVAL_MINUTES * 60)
            
            # Renew lock before syncing (if we're using locks)
            if redis_client and lock_key:
                try:
                    # Fix: Access underlying redis client if using wrapper
                    client = redis_client.redis if hasattr(redis_client, "redis") else redis_client
                    await client.expire(lock_key, 600)
                    logger.debug(f"Lock renewed by worker {worker_pid}")
                except Exception as e:
                    logger.warning(f"Failed to renew lock: {e}")
            
            logger.info("Periodic sync started...")
            try:
                events = await asyncio.wait_for(
                    asyncio.to_thread(sheets.fetch_events),
                    timeout=settings.SYNC_TIMEOUT_SECONDS
                )
                await vector.update_kb(events)
                logger.info(f"Periodic sync complete: {len(events)} events")
            except asyncio.TimeoutError:
                logger.error("Periodic sync timeout")
            
        except asyncio.CancelledError:
            logger.info("Sync scheduler stopped")
            break
        except Exception as e:
            logger.error(f"Periodic sync failed: {e}")


app = FastAPI(
    title=settings.TITLE,
    version=settings.VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression for faster responses
app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(api_router)

# Expose /metrics endpoint
instrumentator.instrument(app).expose(app)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """Serve chat interface."""
    return FileResponse("app/static/chat.html")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.VERSION}


# Metrics endpoint handled by instrumentator


# Dashboard Authentication
security_basic = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security_basic)):
    """Verify dashboard credentials using constant-time comparison."""
    valid_user = secrets.compare_digest(credentials.username, settings.DASHBOARD_USERNAME)
    valid_pass = secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/dashboard")
async def dashboard(username: str = Depends(verify_credentials)):
    """Serve analytics dashboard (protected)."""
    logger.info(f"Dashboard access: {username}")
    return FileResponse("app/static/analytics.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
