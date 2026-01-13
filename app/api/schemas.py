"""Aurora RAG Chatbot - API Schemas (Pydantic models for request/response validation)."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator
import re


# =============================================================================
# ENUMS
# =============================================================================

class Intent(str, Enum):
    """Query intent categories."""
    SCHEDULE = "schedule"
    VENUE = "venue"
    REGISTRATION = "registration"
    RULES = "rules"
    CONTACT = "contact"
    GENERAL = "general"
    GREETING = "greeting"
    FAREWELL = "farewell"
    THANKS = "thanks"
    ACKNOWLEDGMENT = "acknowledgment"
    UNKNOWN = "unknown"


class ConfidenceTier(str, Enum):
    """Response confidence tiers."""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class FeedbackType(str, Enum):
    """User feedback types."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class HealthStatus(str, Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# =============================================================================
# BASE MODELS
# =============================================================================

class BaseResponse(BaseModel):
    """Base response model with common fields."""
    success: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)
    request_id: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ErrorDetail(BaseModel):
    """Error detail structure."""
    code: str
    message: str
    field: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standardized error response."""
    success: bool = False
    error: ErrorDetail
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


# =============================================================================
# CHAT SCHEMAS
# =============================================================================

class ClientData(BaseModel):
    """Client-side data for analytics."""
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    referrer: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class ChatRequest(BaseModel):
    """
    Chat request schema.
    
    Example:
        {
            "query": "What events are happening today?",
            "threshold": 0.5,
            "session_id": "abc123",
            "client_data": {"timezone": "Asia/Kolkata"}
        }
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="User query (1-500 characters)"
    )
    threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold (0.0-1.0)"
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Session identifier for conversation context"
    )
    client_data: Optional[ClientData] = Field(
        default=None,
        description="Optional client-side data for analytics"
    )
    
    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate and sanitize query."""
        v = v.strip()
        if not v:
            raise ValueError("Query cannot be empty")
        
        # Remove excessive whitespace
        v = re.sub(r'\s+', ' ', v)
        
        # Check for suspicious patterns (basic)
        if len(v) > 100 and v.count('.') > 20:
            raise ValueError("Query contains too many special characters")
        
        return v
    
    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate session ID format."""
        if v is None:
            return v
        
        v = v.strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Session ID contains invalid characters")
        
        return v


class ChatResponse(BaseModel):
    """
    Chat response schema.
    
    Example:
        {
            "answer": "There are 5 events happening today...",
            "confidence": 0.85,
            "tier": "High",
            "intent": "schedule",
            "response_time_ms": 150.5,
            "interaction_id": "xyz789",
            "timestamp": "2025-01-10T12:30:45.123Z"
        }
    """
    answer: str = Field(
        ...,
        description="Generated response text"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Response confidence score (0.0-1.0)"
    )
    tier: ConfidenceTier = Field(
        ...,
        description="Confidence tier (High/Medium/Low)"
    )
    intent: Intent = Field(
        ...,
        description="Detected query intent"
    )
    response_time_ms: float = Field(
        ...,
        ge=0.0,
        description="Response generation time in milliseconds"
    )
    interaction_id: str = Field(
        ...,
        description="Unique interaction ID for feedback"
    )
    timestamp: str = Field(
        ...,
        description="Response timestamp (ISO 8601)"
    )
    
    # Optional fields
    sources: Optional[List[str]] = Field(
        default=None,
        description="Source chunk IDs used for response"
    )
    cached: bool = Field(
        default=False,
        description="Whether response was served from cache"
    )


# =============================================================================
# FEEDBACK SCHEMAS
# =============================================================================

class FeedbackRequest(BaseModel):
    """User feedback submission."""
    interaction_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Interaction ID from chat response"
    )
    feedback: FeedbackType = Field(
        ...,
        description="Feedback type (helpful/not_helpful)"
    )
    comment: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional feedback comment"
    )
    
    @field_validator('interaction_id')
    @classmethod
    def validate_interaction_id(cls, v: str) -> str:
        """Validate interaction ID format."""
        v = v.strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Invalid interaction ID format")
        return v


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    success: bool = True
    message: str = "Feedback recorded"


# =============================================================================
# AUTHENTICATION SCHEMAS
# =============================================================================

class LoginRequest(BaseModel):
    """Login credentials."""
    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Username"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Password"
    )


class LoginResponse(BaseModel):
    """Login response with token."""
    token: str = Field(
        ...,
        description="JWT access token"
    )
    token_type: str = Field(
        default="bearer",
        description="Token type"
    )
    expires_in: int = Field(
        ...,
        description="Token expiry in seconds"
    )


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # Subject (user ID)
    exp: int  # Expiration timestamp
    iat: int  # Issued at timestamp
    scope: str = "user"  # Permission scope


# =============================================================================
# ANALYTICS SCHEMAS
# =============================================================================

class InteractionRecord(BaseModel):
    """Single interaction record."""
    id: str
    user_id: Optional[str]
    query: str
    answer: str
    intent: Intent
    confidence: float
    response_time_ms: float
    feedback: Optional[FeedbackType]
    timestamp: datetime
    ip_hash: Optional[str]
    device_type: Optional[str]


class AnalyticsSummary(BaseModel):
    """Analytics dashboard summary."""
    total_interactions: int
    today_interactions: int
    avg_response_time_ms: float
    avg_confidence: float
    helpful_rate: Optional[float]
    intent_distribution: Dict[str, int]
    hourly_distribution: List[int]
    top_queries: List[Dict[str, Any]]


class InteractionsResponse(BaseModel):
    """List of interactions."""
    interactions: List[InteractionRecord]
    total: int
    page: int = 1
    page_size: int = 50


# =============================================================================
# HEALTH CHECK SCHEMAS
# =============================================================================

class ComponentHealthSchema(BaseModel):
    """Component health status."""
    name: str
    status: HealthStatus
    latency_ms: float
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class HealthCheckResponse(BaseModel):
    """Full health check response."""
    status: HealthStatus
    version: str
    timestamp: float
    components: Dict[str, ComponentHealthSchema]


class LivenessResponse(BaseModel):
    """Kubernetes liveness probe response."""
    status: str = "alive"


class ReadinessResponse(BaseModel):
    """Kubernetes readiness probe response."""
    status: str = "ready"


# =============================================================================
# METRICS SCHEMAS
# =============================================================================

class SLAMetrics(BaseModel):
    """SLA-related metrics."""
    request_count: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    availability: float


class CacheStats(BaseModel):
    """Cache statistics."""
    hits: int
    misses: int
    hit_rate: float
    size: int


class APIStats(BaseModel):
    """API usage statistics."""
    status: str
    sla: SLAMetrics
    cache: Optional[CacheStats] = None
    api_keys: Optional[Dict[str, Any]] = None


# =============================================================================
# ABUSE DETECTION SCHEMAS
# =============================================================================

class AbuseStats(BaseModel):
    """Abuse detection statistics."""
    total_checks: int
    total_blocked: int
    block_rate: float
    blocked_ips: int
    recent_violations: List[Dict[str, Any]]


# =============================================================================
# EVENT SCHEMAS
# =============================================================================

class EventBase(BaseModel):
    """Base event information."""
    event_name: str
    event_type: str
    club_name: Optional[str] = None
    description: Optional[str] = None


class EventSchedule(EventBase):
    """Event with schedule information."""
    start_date: str
    end_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    venue: Optional[str] = None
    room: Optional[str] = None


class EventDetails(EventSchedule):
    """Full event details."""
    registration_required: Optional[str] = None
    registration_link: Optional[str] = None
    fee: Optional[str] = None
    certificate_offered: Optional[str] = None
    prerequisites: Optional[str] = None
    max_participants: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class EventListResponse(BaseModel):
    """List of events."""
    events: List[EventSchedule]
    total: int
    date_range: Dict[str, str]


# =============================================================================
# PAGINATION SCHEMAS
# =============================================================================

class PaginationParams(BaseModel):
    """Pagination parameters."""
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=50, ge=1, le=100, description="Items per page")
    sort_by: Optional[str] = Field(default=None, description="Sort field")
    sort_order: Optional[str] = Field(default="desc", pattern="^(asc|desc)$")


class PaginatedResponse(BaseModel):
    """Base paginated response."""
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool


# =============================================================================
# SYNC SCHEMAS
# =============================================================================

class SyncStatus(BaseModel):
    """Data sync status."""
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    status: str
    events_count: int
    error: Optional[str] = None


class SyncTriggerResponse(BaseModel):
    """Manual sync trigger response."""
    success: bool
    message: str
    events_synced: Optional[int] = None
