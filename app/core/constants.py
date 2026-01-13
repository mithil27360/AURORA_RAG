"""
Aurora RAG Chatbot - Constants & Enums

Centralized definitions for error codes, response templates, intent categories,
and other constants used throughout the application.
"""

from enum import Enum, IntEnum
from typing import Dict, List, Set, Tuple


# =============================================================================
# ERROR CODES & MESSAGES
# =============================================================================

class ErrorCode(IntEnum):
    """Application error codes for consistent error handling."""
    # Success (1xxx)
    SUCCESS = 1000
    
    # Client errors (4xxx)
    BAD_REQUEST = 4000
    INVALID_QUERY = 4001
    QUERY_TOO_LONG = 4002
    QUERY_TOO_SHORT = 4003
    INVALID_SESSION = 4004
    MISSING_REQUIRED_FIELD = 4005
    
    # Authentication/Authorization (41xx)
    UNAUTHORIZED = 4100
    INVALID_CREDENTIALS = 4101
    TOKEN_EXPIRED = 4102
    INSUFFICIENT_PERMISSIONS = 4103
    
    # Rate limiting (42xx)
    RATE_LIMITED = 4200
    QUOTA_EXCEEDED = 4201
    CONCURRENT_LIMIT = 4202
    
    # Abuse detection (43xx)
    ABUSE_DETECTED = 4300
    BLOCKED_IP = 4301
    BLOCKED_USER = 4302
    SUSPICIOUS_ACTIVITY = 4303
    
    # Server errors (5xxx)
    INTERNAL_ERROR = 5000
    LLM_ERROR = 5001
    VECTOR_DB_ERROR = 5002
    REDIS_ERROR = 5003
    DATABASE_ERROR = 5004
    SHEETS_SYNC_ERROR = 5005
    
    # Timeout errors (52xx)
    LLM_TIMEOUT = 5200
    VECTOR_TIMEOUT = 5201
    REDIS_TIMEOUT = 5202
    SYNC_TIMEOUT = 5203


ERROR_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.SUCCESS: "Success",
    ErrorCode.BAD_REQUEST: "Invalid request format",
    ErrorCode.INVALID_QUERY: "Query contains invalid characters or format",
    ErrorCode.QUERY_TOO_LONG: "Query exceeds maximum length of {max_length} characters",
    ErrorCode.QUERY_TOO_SHORT: "Query must be at least {min_length} characters",
    ErrorCode.INVALID_SESSION: "Session is invalid or expired",
    ErrorCode.MISSING_REQUIRED_FIELD: "Required field '{field}' is missing",
    ErrorCode.UNAUTHORIZED: "Authentication required",
    ErrorCode.INVALID_CREDENTIALS: "Invalid username or password",
    ErrorCode.TOKEN_EXPIRED: "Authentication token has expired",
    ErrorCode.INSUFFICIENT_PERMISSIONS: "Insufficient permissions for this action",
    ErrorCode.RATE_LIMITED: "Rate limit exceeded. Please try again in {retry_after} seconds",
    ErrorCode.QUOTA_EXCEEDED: "Daily quota exceeded. Resets at midnight UTC",
    ErrorCode.CONCURRENT_LIMIT: "Too many concurrent requests. Please wait",
    ErrorCode.ABUSE_DETECTED: "Request blocked due to policy violation",
    ErrorCode.BLOCKED_IP: "Access denied from this IP address",
    ErrorCode.BLOCKED_USER: "Account temporarily suspended",
    ErrorCode.SUSPICIOUS_ACTIVITY: "Suspicious activity detected. Please verify your identity",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again",
    ErrorCode.LLM_ERROR: "Unable to generate response. Please try again",
    ErrorCode.VECTOR_DB_ERROR: "Knowledge base temporarily unavailable",
    ErrorCode.REDIS_ERROR: "Session service temporarily unavailable",
    ErrorCode.DATABASE_ERROR: "Database temporarily unavailable",
    ErrorCode.SHEETS_SYNC_ERROR: "Unable to sync event data",
    ErrorCode.LLM_TIMEOUT: "Response generation timed out. Please try a simpler query",
    ErrorCode.VECTOR_TIMEOUT: "Search timed out. Please try again",
    ErrorCode.REDIS_TIMEOUT: "Session lookup timed out",
    ErrorCode.SYNC_TIMEOUT: "Data sync timed out",
}


# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

class Intent(str, Enum):
    """User intent categories for query classification."""
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


INTENT_KEYWORDS: Dict[Intent, Set[str]] = {
    Intent.SCHEDULE: {
        "when", "time", "schedule", "timing", "date", "day", "start", "end",
        "duration", "how long", "today", "tomorrow", "yesterday", "events",
        "list", "all events", "show events", "what events"
    },
    Intent.VENUE: {
        "where", "venue", "location", "place", "room", "hall", "building",
        "address", "map", "directions", "floor"
    },
    Intent.REGISTRATION: {
        "register", "registration", "sign up", "signup", "enroll", "join",
        "participate", "apply", "fee", "cost", "price", "free", "paid"
    },
    Intent.RULES: {
        "rules", "guidelines", "instructions", "requirements", "prerequisites",
        "eligibility", "allowed", "prohibited", "bring", "carry"
    },
    Intent.CONTACT: {
        "contact", "phone", "email", "reach", "call", "coordinator",
        "organizer", "poc", "point of contact", "help desk"
    },
    Intent.GREETING: {
        "hi", "hello", "hey", "hlo", "hy", "good morning", "good afternoon",
        "good evening", "greetings", "namaste", "hola"
    },
    Intent.FAREWELL: {
        "bye", "goodbye", "see you", "cya", "later", "take care",
        "good night", "gotta go", "leaving"
    },
    Intent.THANKS: {
        "thanks", "thank you", "thx", "tks", "appreciate", "grateful",
        "much appreciated"
    },
    Intent.ACKNOWLEDGMENT: {
        "ok", "okay", "k", "cool", "great", "nice", "awesome", "perfect",
        "got it", "understood", "alright", "fine", "good", "yes", "yup",
        "sure", "right"
    },
}


# =============================================================================
# RESPONSE TEMPLATES
# =============================================================================

class ResponseTemplate:
    """Pre-defined response templates for common scenarios."""
    
    # Greetings
    GREETING_FIRST = "Hello! Welcome to Aurora Fest 2025. I'm here to help you with event schedules, workshops, hackathons, and registration details. How can I assist you today?"
    GREETING_REPEAT = "How can I help?"
    
    # Farewells
    FAREWELL = "Have a great day! Feel free to return if you have more questions about Aurora Fest."
    
    # Thanks
    THANKS_RESPONSE = "You're welcome! Is there anything else I can help you with regarding Aurora Fest?"
    
    # Acknowledgments
    ACKNOWLEDGMENT = "Glad to help! Anything else about Aurora Fest?"
    
    # Errors
    ERROR_GENERIC = "I'm having trouble right now. Please try again in a moment."
    ERROR_NO_CONTEXT = "I couldn't find specific information about that in the festival guide. Could you try rephrasing your question?"
    ERROR_UNCLEAR = "I didn't quite catch that. Could you rephrase your question?"
    ERROR_TIMEOUT = "I'm taking too long to respond. Please try asking your question again."
    
    # Abuse
    ABUSE_SOFT = "I can't process that request. Please keep queries related to Aurora Fest events."
    ABUSE_BLOCKED = "Access temporarily restricted. Please try again later."
    
    # Unknown
    UNKNOWN_EVENT = "I couldn't find any information about '{event}' in the festival guide. Would you like to see a list of all events?"
    NO_EVENTS_DATE = "No events are scheduled for {date}."
    NOT_ANNOUNCED = "This information hasn't been officially announced yet. Please check back closer to the event."


# =============================================================================
# CACHE WARMUP DATA
# =============================================================================

COMMON_QNA: List[Tuple[str, str]] = [
    # Queries -> ResponseTemplate
    ("hi", ResponseTemplate.GREETING_REPEAT),
    ("hello", ResponseTemplate.GREETING_REPEAT),
    ("hey", ResponseTemplate.GREETING_REPEAT),
    ("thanks", ResponseTemplate.THANKS_RESPONSE),
    ("thank you", ResponseTemplate.THANKS_RESPONSE),
    ("bye", ResponseTemplate.FAREWELL),
    ("goodbye", ResponseTemplate.FAREWELL),
    ("ok", ResponseTemplate.ACKNOWLEDGMENT),
    ("okay", ResponseTemplate.ACKNOWLEDGMENT),
    ("great", ResponseTemplate.ACKNOWLEDGMENT),
    ("cool", ResponseTemplate.ACKNOWLEDGMENT),
]


# =============================================================================
# CONFIDENCE TIERS
# =============================================================================

class ConfidenceTier(str, Enum):
    """Response confidence tiers for quality indication."""
    HIGH = "High"      # >= 0.8
    MEDIUM = "Medium"  # >= 0.5
    LOW = "Low"        # < 0.5


def get_confidence_tier(score: float) -> ConfidenceTier:
    """Get confidence tier from numeric score."""
    if score >= 0.8:
        return ConfidenceTier.HIGH
    elif score >= 0.5:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW


# =============================================================================
# CHUNK TYPES
# =============================================================================

class ChunkType(str, Enum):
    """Vector store chunk types for filtering."""
    SCHEDULE = "schedule"
    VENUE = "venue"
    GENERAL = "general"
    RULES = "rules"
    FAQ = "faq"
    CONTACT = "contact"
    EVENT_LIST = "event_list"
    ABOUT = "about"
    STATIC = "static"


# =============================================================================
# ABUSE SEVERITY LEVELS
# =============================================================================

class AbuseSeverity(IntEnum):
    """Abuse detection severity levels."""
    NONE = 0
    LOW = 1       # Minor issues, log only
    MEDIUM = 2    # Soft refusal, warning
    HIGH = 3      # Hard block, temporary ban
    CRITICAL = 4  # Permanent ban, report


# =============================================================================
# RATE LIMIT TIERS
# =============================================================================

class RateLimitTier(str, Enum):
    """Rate limiting tiers for different user types."""
    ANONYMOUS = "anonymous"    # 30 req/min
    AUTHENTICATED = "authenticated"  # 60 req/min
    PREMIUM = "premium"        # 120 req/min
    ADMIN = "admin"            # Unlimited


RATE_LIMITS: Dict[RateLimitTier, Dict[str, int]] = {
    RateLimitTier.ANONYMOUS: {"requests_per_minute": 30, "burst": 5},
    RateLimitTier.AUTHENTICATED: {"requests_per_minute": 60, "burst": 10},
    RateLimitTier.PREMIUM: {"requests_per_minute": 120, "burst": 20},
    RateLimitTier.ADMIN: {"requests_per_minute": 10000, "burst": 100},
}


# =============================================================================
# QUERY LIMITS
# =============================================================================

QUERY_MIN_LENGTH = 1
QUERY_MAX_LENGTH = 500
QUERY_MAX_WORDS = 100

HISTORY_MAX_TURNS = 10
CONTEXT_MAX_CHUNKS = 15
CONTEXT_MAX_TOKENS = 2000


# =============================================================================
# TIMEOUT CONFIGURATIONS (seconds)
# =============================================================================

class Timeouts:
    """Timeout configurations for various operations."""
    LLM_DEFAULT = 30.0
    LLM_FAST = 10.0
    VECTOR_SEARCH = 10.0
    REDIS_OPERATION = 2.0
    DATABASE_QUERY = 5.0
    SHEETS_SYNC = 60.0
    HEALTH_CHECK = 5.0
    REQUEST_TOTAL = 45.0


# =============================================================================
# RETRY CONFIGURATIONS
# =============================================================================

class RetryConfig:
    """Retry configurations for external services."""
    LLM_MAX_RETRIES = 3
    LLM_INITIAL_DELAY = 1.0
    LLM_MAX_DELAY = 10.0
    LLM_EXPONENTIAL_BASE = 2.0
    
    VECTOR_MAX_RETRIES = 2
    VECTOR_INITIAL_DELAY = 0.5
    
    REDIS_MAX_RETRIES = 2
    REDIS_INITIAL_DELAY = 0.1


# =============================================================================
# FEATURE FLAGS (Default values, override via environment)
# =============================================================================

class FeatureFlags:
    """Feature flags for gradual rollouts."""
    ENABLE_STREAMING = False
    ENABLE_SEMANTIC_CACHE = True
    ENABLE_HYBRID_SEARCH = True
    ENABLE_CONVERSATION_CONTEXT = True
    ENABLE_ANALYTICS = True
    ENABLE_A_B_TESTING = False
    ENABLE_ML_TOXICITY = False
    ENABLE_RATE_LIMITING = True
    DEBUG_MODE = False


# =============================================================================
# HTTP STATUS MAPPINGS
# =============================================================================

HTTP_STATUS_MAP: Dict[ErrorCode, int] = {
    ErrorCode.SUCCESS: 200,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.INVALID_QUERY: 400,
    ErrorCode.QUERY_TOO_LONG: 400,
    ErrorCode.QUERY_TOO_SHORT: 400,
    ErrorCode.INVALID_SESSION: 400,
    ErrorCode.MISSING_REQUIRED_FIELD: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.INSUFFICIENT_PERMISSIONS: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.QUOTA_EXCEEDED: 429,
    ErrorCode.CONCURRENT_LIMIT: 429,
    ErrorCode.ABUSE_DETECTED: 400,
    ErrorCode.BLOCKED_IP: 403,
    ErrorCode.BLOCKED_USER: 403,
    ErrorCode.SUSPICIOUS_ACTIVITY: 403,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.LLM_ERROR: 503,
    ErrorCode.VECTOR_DB_ERROR: 503,
    ErrorCode.REDIS_ERROR: 503,
    ErrorCode.DATABASE_ERROR: 503,
    ErrorCode.SHEETS_SYNC_ERROR: 503,
    ErrorCode.LLM_TIMEOUT: 504,
    ErrorCode.VECTOR_TIMEOUT: 504,
    ErrorCode.REDIS_TIMEOUT: 504,
    ErrorCode.SYNC_TIMEOUT: 504,
}


# =============================================================================
# EVENT METADATA FIELDS
# =============================================================================

EVENT_REQUIRED_FIELDS = [
    "event_name",
    "event_type",
    "start_date",
]

EVENT_OPTIONAL_FIELDS = [
    "end_date",
    "start_time",
    "end_time",
    "venue",
    "room",
    "club_name",
    "description",
    "registration_required",
    "registration_link",
    "fee",
    "certificate_offered",
    "prerequisites",
    "max_participants",
    "contact_name",
    "contact_email",
    "contact_phone",
    "day_num",
]


# =============================================================================
# STATIC CONTENT IDS
# =============================================================================

STATIC_CHUNK_IDS = [
    "about_aurora",
    "about_chief_guest",
    "about_iste",
    "contact_info",
    "general_rules",
    "venue_info",
]
