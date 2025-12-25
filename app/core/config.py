
import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    TITLE: str = "Aurora Fest RAG Chatbot"
    VERSION: str = "2.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    STRICT_MODE: bool = True

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    CHROMA_PATH: Path = BASE_DIR / "chroma_data"
    DB_PATH: Path = BASE_DIR / "rag_interactions.db"
    
    # Credentials
    GROQ_API_KEY: str
    GOOGLE_SHEETS_ID: str
    GOOGLE_CREDS_FILE: str = "credentials.json"
    
    # Security
    DASHBOARD_USERNAME: str = "admin"
    DASHBOARD_PASSWORD: str = "aurora2025"
    ALLOWED_ORIGINS: str = "http://localhost:8000"

    # Business Logic Constants
    CONFIDENCE_THRESHOLD: float = 0.05
    TOP_K_RESULTS: int = 50
    LLM_TEMPERATURE: float = 0.3
    
    # Production Limits (Optimized for 200+ concurrent users)
    MAX_CONVERSATION_USERS: int = 10000
    MAX_CACHE_ENTRIES: int = 5000
    CACHE_TTL_SECONDS: int = 300
    LLM_TIMEOUT_SECONDS: float = 30.0  # Increased for high load
    SYNC_TIMEOUT_SECONDS: float = 60.0
    SYNC_INTERVAL_MINUTES: int = 5
    AUTO_SYNC_ENABLED: bool = True
    
    # Rate Limiting (per IP)
    RATE_LIMIT_CHAT: str = "60/minute"  # 60 messages/min per user (1/sec is plenty)
    RATE_LIMIT_BURST: str = "10/second"  # Allow burst of 10
    
    # Worker Settings
    WORKERS: int = 4  # 4 workers for 200 users = ~50 concurrent per worker
    MAX_CONNECTIONS: int = 500  # Max concurrent connections

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0" 

    class Config:
        env_file = ".env"
        extra = "ignore" # Allow extra env vars

settings = Settings()
