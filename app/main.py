"""Aurora Fest RAG Chatbot - Main Application Entry Point."""

import logging
import asyncio
import secrets

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
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
    
    if settings.AUTO_SYNC_ENABLED:
        asyncio.create_task(_initial_sync(sheets, vector))
        asyncio.create_task(_periodic_sync_scheduler(sheets, vector))
        logger.info(f"Auto-sync enabled: interval={settings.SYNC_INTERVAL_MINUTES}m")

    yield
    
    logger.info("Shutting down...")


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


async def _periodic_sync_scheduler(sheets, vector):
    """Background scheduler for periodic data refresh."""
    while True:
        try:
            await asyncio.sleep(settings.SYNC_INTERVAL_MINUTES * 60)
            
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

app.include_router(api_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """Serve chat interface."""
    return FileResponse("app/static/chat.html")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.VERSION}


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
