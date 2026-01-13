"""
Aurora RAG Chatbot - Configuration Management

Simplified, grouped configuration with validation and fail-fast behavior.

Design Decision: Features are gated by design, not implemented until usage justification.
Removed features: A/B Testing, Voice Input, Multilingual, Personalization, Circuit Breaker.
"""

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator, model_validator, computed_field
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    """Application environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


# =============================================================================
# GROUPED CONFIGURATION CLASSES
# =============================================================================

class ServerConfig(BaseModel):
    """Server configuration with sensible defaults."""
    host: str = "0.0.0.0"
    port: int = Field(default=8001, ge=1, le=65535)
    workers: int = Field(default=4, ge=1, le=32)
    max_connections: int = Field(default=500, ge=10, le=10000)
    keep_alive: int = Field(default=5, ge=1, le=120)


class LLMConfig(BaseModel):
    """LLM configuration with validation."""
    model: str = "llama-3.1-8b-instant"
    fallback_model: str = "llama-3.1-70b-versatile"
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=100, le=4096)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    max_retries: int = Field(default=3, ge=0, le=10)


class VectorConfig(BaseModel):
    """Vector store configuration."""
    confidence_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_k: int = Field(default=50, ge=1, le=100)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    collection_prefix: str = "Aurora_v_"


class CacheConfig(BaseModel):
    """Cache configuration for L1/L2/Semantic caching."""
    enabled: bool = True
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    max_entries: int = Field(default=10000, ge=100, le=100000)
    semantic_enabled: bool = True
    semantic_threshold: float = Field(default=0.85, ge=0.5, le=1.0)


class RedisConfig(BaseModel):
    """Redis configuration."""
    url: str = "redis://localhost:6379/0"
    max_connections: int = Field(default=50, ge=1, le=500)
    timeout: float = Field(default=2.0, ge=0.5, le=30.0)


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""
    enabled: bool = True
    requests_per_minute: int = Field(default=60, ge=1, le=1000)
    burst: int = Field(default=10, ge=1, le=100)


class SecurityConfig(BaseModel):
    """Security configuration."""
    secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = Field(default=24, ge=1, le=168)
    dashboard_username: str = "admin"
    dashboard_password: str = Field(default="aurora2025")
    allowed_origins: List[str] = ["http://localhost:8000", "http://localhost:3000"]
    enable_hsts: bool = True


class SyncConfig(BaseModel):
    """Data sync configuration."""
    enabled: bool = True
    interval_minutes: int = Field(default=5, ge=1, le=60)
    timeout_seconds: float = Field(default=60.0, ge=10.0, le=300.0)


class AbuseConfig(BaseModel):
    """Abuse detection configuration."""
    enabled: bool = True
    score_threshold: int = Field(default=20, ge=5, le=100)
    block_duration_minutes: int = Field(default=15, ge=1, le=1440)
    max_violations: int = Field(default=5, ge=1, le=20)


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = "json"  # "json" or "text"


# =============================================================================
# MAIN SETTINGS CLASS
# =============================================================================

class Settings(BaseSettings):
    """
    Application settings with grouped configuration.
    
    All settings are loaded from environment variables and .env file.
    Fail-fast validation ensures misconfiguration is caught at startup.
    """
    
    # Application metadata
    TITLE: str = "Aurora Fest RAG Chatbot"
    VERSION: str = "3.0.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    STRICT_MODE: bool = True

    # Grouped configurations
    server: ServerConfig = ServerConfig()
    llm: LLMConfig = LLMConfig()
    vector: VectorConfig = VectorConfig()
    cache: CacheConfig = CacheConfig()
    redis: RedisConfig = RedisConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    security: SecurityConfig = SecurityConfig()
    sync: SyncConfig = SyncConfig()
    abuse: AbuseConfig = AbuseConfig()
    logging: LoggingConfig = LoggingConfig()

    # Credentials (required)
    GROQ_API_KEY: str = Field(default="")
    GOOGLE_SHEETS_ID: str = Field(default="")

    GOOGLE_CREDS_FILE: str = "config/credentials.json"
    
    # Dashboard Credentials (loaded from env)
    DASHBOARD_USERNAME: str = Field(default="admin")
    DASHBOARD_PASSWORD: str = Field(default="aurora2025")
    SECRET_KEY: str = Field(default="change-me-in-production")

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # Core feature flags (only essential ones)
    FEATURE_CONVERSATION_CONTEXT: bool = True
    FEATURE_ANALYTICS: bool = True
    
    # Observability
    ENABLE_METRICS: bool = True

    # Query limits
    QUERY_MIN_LENGTH: int = 1
    QUERY_MAX_LENGTH: int = 500

    # ==========================================================================
    # COMPUTED PROPERTIES
    # ==========================================================================

    @property
    def DATA_DIR(self) -> Path:
        return self.BASE_DIR / "data"

    @property
    def CONFIG_DIR(self) -> Path:
        return self.BASE_DIR / "config"

    @property
    def LOGS_DIR(self) -> Path:
        return self.BASE_DIR / "logs"

    @property
    def CHROMA_PATH(self) -> Path:
        return self.DATA_DIR / "chroma_data"

    @property
    def DB_PATH(self) -> Path:
        return self.DATA_DIR / "rag_interactions.db"

    # ==========================================================================
    # VALIDATORS
    # ==========================================================================

    @field_validator('GROQ_API_KEY')
    @classmethod
    def validate_groq_key(cls, v):
        """Warn if GROQ_API_KEY is empty."""
        if not v:
            import logging
            logging.warning("GROQ_API_KEY not set - LLM features will be disabled")
        return v

    @model_validator(mode='after')
    def validate_and_sync_security(self):
        """Sync credentials and validate production security."""
        # Sync credentials first
        if self.DASHBOARD_USERNAME != "admin":
            self.security.dashboard_username = self.DASHBOARD_USERNAME
        if self.DASHBOARD_PASSWORD != "aurora2025":
            self.security.dashboard_password = self.DASHBOARD_PASSWORD
        if self.SECRET_KEY != "change-me-in-production":
            self.security.secret_key = self.SECRET_KEY

        # Fail-fast validation for production environment
        if self.ENVIRONMENT == Environment.PRODUCTION:
            if self.security.secret_key == "change-me-in-production":
                raise ValueError("SECRET_KEY must be changed in production")
            if len(self.security.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if self.security.dashboard_password == "aurora2025":
                raise ValueError("DASHBOARD_PASSWORD must be changed in production")
        return self

    # ==========================================================================
    # PYDANTIC CONFIG
    # ==========================================================================

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = True
        env_nested_delimiter = "__"  # Allows SERVER__PORT=8001 in .env

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == Environment.PRODUCTION

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == Environment.DEVELOPMENT



    def get_log_level_int(self) -> int:
        """Get numeric log level."""
        import logging as log_module
        return getattr(log_module, self.logging.level.upper(), log_module.INFO)

    def ensure_directories(self):
        """Create required directories if they don't exist."""
        for dir_path in [self.DATA_DIR, self.CONFIG_DIR, self.LOGS_DIR]:
            if dir_path:
                dir_path.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name: str):
        """Dynamic attribute access for backward compatibility."""
        # Mapping of flat names to grouped config paths
        LEGACY_MAP = {
            # LLM
            'GROQ_API_KEY': lambda s: s.llm.api_key,
            'LLM_MODEL': lambda s: s.llm.model,
            'LLM_TEMPERATURE': lambda s: s.llm.temperature,
            'LLM_MAX_TOKENS': lambda s: s.llm.max_tokens,
            'LLM_TIMEOUT_SECONDS': lambda s: s.llm.timeout_seconds,
            'STRICT_MODE': lambda s: getattr(s.llm, 'strict_mode', True),
            # Vector
            'CONFIDENCE_THRESHOLD': lambda s: s.vector.confidence_threshold,
            'TOP_K_RESULTS': lambda s: s.vector.top_k,
            # Cache
            'ENABLE_CACHE': lambda s: s.cache.enabled,
            'CACHE_TTL_SECONDS': lambda s: s.cache.ttl_seconds,
            'ENABLE_SEMANTIC_CACHE': lambda s: s.cache.semantic_enabled,
            'SEMANTIC_CACHE_THRESHOLD': lambda s: s.cache.semantic_threshold,
            # Redis
            'REDIS_URL': lambda s: s.redis.url,
            # Rate Limit
            'ENABLE_RATE_LIMITING': lambda s: s.rate_limit.enabled,
            'RATE_LIMIT_CHAT': lambda s: f"{s.rate_limit.requests_per_minute}/minute",
            # Security
            'SECRET_KEY': lambda s: s.security.secret_key,
            'DASHBOARD_USERNAME': lambda s: s.security.dashboard_username,
            'DASHBOARD_PASSWORD': lambda s: s.security.dashboard_password,
            'ALLOWED_ORIGINS': lambda s: s.security.allowed_origins,
            'ENABLE_HSTS': lambda s: True,
            'HSTS_MAX_AGE': lambda s: 31536000,
            'ENABLE_CSP': lambda s: True,
            # Sync
            'AUTO_SYNC_ENABLED': lambda s: s.sync.enabled,
            'SYNC_INTERVAL_MINUTES': lambda s: s.sync.interval_minutes,
            'SYNC_TIMEOUT_SECONDS': lambda s: getattr(s.sync, 'timeout_seconds', 60),
            # Abuse
            'ENABLE_ABUSE_DETECTION': lambda s: s.abuse.enabled,
            # Logging
            'LOG_LEVEL': lambda s: s.logging.level,
            # Misc
            'MAX_CONVERSATION_USERS': lambda s: 10000,
            'SESSION_TTL_SECONDS': lambda s: 3600,
            'MAX_HISTORY_TURNS': lambda s: 10,
            'DEBUG': lambda s: s.ENVIRONMENT == Environment.DEVELOPMENT,
        }
        
        if name in LEGACY_MAP:
            return LEGACY_MAP[name](self)
        
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
# =============================================================================
# SINGLETON ACCESS
# =============================================================================

@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Uses lru_cache for performance - settings are loaded once
    and reused throughout the application lifecycle.
    """
    return Settings()


# Global settings instance for backward compatibility
settings = get_settings()


# =============================================================================
# BACKWARD COMPATIBILITY (via module-level globals)
# =============================================================================
# For legacy code that imports these directly.
# New code should use: settings.server.host, settings.llm.model, etc.

HOST = settings.server.host
PORT = settings.server.port
WORKERS = settings.server.workers
LLM_MODEL = settings.llm.model
LLM_TEMPERATURE = settings.llm.temperature
LLM_MAX_TOKENS = settings.llm.max_tokens
LLM_TIMEOUT_SECONDS = settings.llm.timeout_seconds
CONFIDENCE_THRESHOLD = settings.vector.confidence_threshold
TOP_K_RESULTS = settings.vector.top_k
ENABLE_CACHE = settings.cache.enabled
CACHE_TTL_SECONDS = settings.cache.ttl_seconds
ENABLE_SEMANTIC_CACHE = settings.cache.semantic_enabled
SEMANTIC_CACHE_THRESHOLD = settings.cache.semantic_threshold
REDIS_URL = settings.redis.url
ENABLE_RATE_LIMITING = settings.rate_limit.enabled
SECRET_KEY = settings.security.secret_key
DASHBOARD_USERNAME = settings.security.dashboard_username
DASHBOARD_PASSWORD = settings.security.dashboard_password
ALLOWED_ORIGINS = settings.security.allowed_origins
AUTO_SYNC_ENABLED = settings.sync.enabled
SYNC_INTERVAL_MINUTES = settings.sync.interval_minutes
ENABLE_ABUSE_DETECTION = settings.abuse.enabled
LOG_LEVEL = settings.logging.level
