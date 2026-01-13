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

# Active connections
active_connections = Gauge(
    'active_connections',
    'Number of active connections',
    registry=registry
)

def get_registry():
    """Get the metrics registry"""
    return registry

def generate_metrics():
    """Generate metrics in Prometheus format"""
    return generate_latest(registry)
