"""
Prometheus Metrics for Aurora RAG Chatbot
"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest

# Create registry
registry = CollectorRegistry()

# Request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=registry
)

chat_requests_total = Counter(
    'chat_requests_total',
    'Total chat requests',
    ['intent', 'cached'],
    registry=registry
)

# Latency metrics
request_duration_seconds = Histogram(
    'request_duration_seconds',
    'Request duration in seconds',
    ['endpoint'],
    registry=registry
)

chat_response_time_ms = Histogram(
    'chat_response_time_ms',
    'Chat response time in milliseconds',
    ['intent', 'tier'],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000],
    registry=registry
)

# Cache metrics
cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['tier'],
    registry=registry
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses',
    registry=registry
)

# Quality metrics
INTENT_CONFIDENCE = Histogram(
    'intent_confidence',
    'Confidence score distribution by intent',
    ['intent'],
    buckets=[0.1, 0.3, 0.5, 0.7, 0.85, 0.95, 1.0],
    registry=registry
)

EMPTY_RESPONSES = Counter(
    'empty_responses_total',
    'Empty or fallback responses',
    registry=registry
)

# ✅ NEW: Cost tracking metrics for operational visibility
token_usage_total = Counter(
    'token_usage_total',
    'Total tokens consumed',
    ['model', 'type'],  # type: prompt or completion
    registry=registry
)

api_cost_dollars = Counter(
    'api_cost_dollars_total',
    'Total estimated API cost in dollars',
    ['service'],  # groq, embedding, etc.
    registry=registry
)

cache_savings_dollars = Counter(
    'cache_savings_dollars_total',
    'Cost saved by cache hits (estimated)',
    registry=registry
)

# Active connections
active_connections = Gauge(
    'active_connections',
    'Number of active connections',
    registry=registry
)

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE-SOURCED METRICS (Accurate historical data from SQLite)
# These are Gauges that get updated periodically from the actual database
# NOTE: Using DEFAULT Prometheus registry (no registry= param) so these appear
#       on the /metrics endpoint exposed by prometheus-fastapi-instrumentator
# ═══════════════════════════════════════════════════════════════════════════════

# Core stats from database - using DEFAULT registry for /metrics visibility
db_total_queries = Gauge(
    'aurora_db_total_queries',
    'Total number of queries from database (accurate count)'
)

db_avg_confidence = Gauge(
    'aurora_db_avg_confidence',
    'Average confidence score from database (0-1)'
)

db_avg_latency_ms = Gauge(
    'aurora_db_avg_latency_ms',
    'Average response latency in milliseconds from database'
)

db_cache_hit_rate = Gauge(
    'aurora_db_cache_hit_rate',
    'Cache hit rate percentage from database'
)

db_low_confidence_count = Gauge(
    'aurora_db_low_confidence_count',
    'Number of queries with confidence below 50%'
)

# Intent distribution from database
db_intent_count = Gauge(
    'aurora_db_intent_count',
    'Query count by intent from database',
    ['intent']
)

# Feedback stats from database
db_feedback_helpful = Gauge(
    'aurora_db_feedback_helpful',
    'Number of helpful feedback responses'
)

db_feedback_not_helpful = Gauge(
    'aurora_db_feedback_not_helpful',
    'Number of not helpful feedback responses'
)

# Device/Browser/OS distribution
db_device_count = Gauge(
    'aurora_db_device_count',
    'Query count by device type from database',
    ['device_type']
)

db_country_count = Gauge(
    'aurora_db_country_count',
    'Query count by country from database',
    ['country']
)


def update_db_metrics(stats: dict):
    """Update database-sourced Gauge metrics from stats dictionary.
    
    Call this periodically or on each /metrics request to sync with DB.
    """
    if not stats:
        return
    
    # Legacy analytics
    legacy = stats.get('legacy_analytics', {})
    db_total_queries.set(legacy.get('total_queries', 0))
    db_avg_latency_ms.set(legacy.get('avg_response_time', 0))
    
    # Cache stats
    cache = stats.get('cache_stats', {})
    db_cache_hit_rate.set(cache.get('cache_hit_rate', 0))
    
    # Production stats
    prod = stats.get('production_stats', {})
    db_avg_confidence.set(prod.get('avg_confidence', 0))
    db_low_confidence_count.set(prod.get('low_confidence_count', 0))
    
    # Intent distribution
    for intent, count in prod.get('top_intents', {}).items():
        db_intent_count.labels(intent=intent).set(count)
    
    # Feedback stats
    feedback = stats.get('feedback_stats', {})
    db_feedback_helpful.set(feedback.get('thumbs_up', 0))
    db_feedback_not_helpful.set(feedback.get('thumbs_down', 0))


def get_registry():
    """Get the metrics registry"""
    return registry

def generate_metrics():
    """Generate metrics in Prometheus format"""
    return generate_latest(registry)

