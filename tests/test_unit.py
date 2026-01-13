"""Aurora RAG Chatbot - Unit Tests for all services."""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch('app.core.config.settings') as mock:
        mock.CONFIDENCE_THRESHOLD = 0.5
        mock.TOP_K_RESULTS = 10
        mock.LLM_TIMEOUT_SECONDS = 30.0
        mock.LLM_MAX_TOKENS = 1000
        mock.LLM_TEMPERATURE = 0.3
        mock.MAX_CONVERSATION_USERS = 1000
        mock.SESSION_TTL_SECONDS = 3600
        mock.MAX_HISTORY_TURNS = 10
        mock.DEBUG = True
        mock.ENVIRONMENT = Mock()
        mock.ENVIRONMENT.value = "development"
        mock.is_development = Mock(return_value=True)
        yield mock


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)
    return redis


# =============================================================================
# CONSTANTS TESTS
# =============================================================================

class TestConstants:
    """Tests for constants module."""
    
    def test_error_codes_complete(self):
        """Verify all error codes have messages."""
        from app.core.constants import ErrorCode, ERROR_MESSAGES
        
        for code in ErrorCode:
            assert code in ERROR_MESSAGES, f"Missing message for {code}"
    
    def test_http_status_mapping(self):
        """Verify HTTP status mappings are valid."""
        from app.core.constants import ErrorCode, HTTP_STATUS_MAP
        
        for code in ErrorCode:
            assert code in HTTP_STATUS_MAP, f"Missing HTTP status for {code}"
            status = HTTP_STATUS_MAP[code]
            assert 100 <= status <= 599, f"Invalid HTTP status {status}"
    
    def test_intent_keywords_coverage(self):
        """Verify intent keywords are defined."""
        from app.core.constants import Intent, INTENT_KEYWORDS
        
        # At least these intents should have keywords
        expected = [Intent.SCHEDULE, Intent.VENUE, Intent.GREETING]
        for intent in expected:
            assert intent in INTENT_KEYWORDS
            assert len(INTENT_KEYWORDS[intent]) > 0
    
    def test_confidence_tier_function(self):
        """Test confidence tier calculation."""
        from app.core.constants import get_confidence_tier, ConfidenceTier
        
        assert get_confidence_tier(0.9) == ConfidenceTier.HIGH
        assert get_confidence_tier(0.7) == ConfidenceTier.MEDIUM
        assert get_confidence_tier(0.3) == ConfidenceTier.LOW


# =============================================================================
# CACHE SERVICE TESTS
# =============================================================================

class TestL1Cache:
    """Tests for L1 in-memory cache."""
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_basic_get_set(self):
        """Test basic cache operations."""
        from app.services.cache import L1Cache
        
        cache = L1Cache(max_size=100, default_ttl=60.0)
        
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        
        assert result == "value1"
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_cache_miss(self):
        """Test cache miss returns None."""
        from app.services.cache import L1Cache
        
        cache = L1Cache(max_size=100, default_ttl=60.0)
        
        result = await cache.get("nonexistent")
        assert result is None
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_cache_expiry(self):
        """Test cache entry expiry."""
        from app.services.cache import L1Cache
        
        cache = L1Cache(max_size=100, default_ttl=0.1)  # 100ms TTL
        
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"
        
        await asyncio.sleep(0.2)  # Wait for expiry
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_lru_eviction(self):
        """Test LRU eviction when at capacity."""
        from app.services.cache import L1Cache
        
        cache = L1Cache(max_size=3, default_ttl=60.0)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        await cache.get("key1")
        
        # Add key4, should evict key2 (least recently used)
        await cache.set("key4", "value4")
        
        assert await cache.get("key1") == "value1"  # Still present
        assert await cache.get("key2") is None  # Evicted
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete(self):
        """Test cache delete."""
        from app.services.cache import L1Cache
        
        cache = L1Cache(max_size=100, default_ttl=60.0)
        
        await cache.set("key1", "value1")
        assert await cache.delete("key1") is True
        assert await cache.get("key1") is None
        assert await cache.delete("key1") is False  # Already deleted


# =============================================================================
# ABUSE DETECTION TESTS
# =============================================================================

class TestAbuseDetection:
    """Tests for abuse detection service."""
    
    def test_sql_injection_detection(self):
        """Test SQL injection pattern detection."""
        from app.services.abuse import AbuseDetector
        
        detector = AbuseDetector()
        
        # Should be flagged
        status, reason, data = detector.process_request("127.0.0.1", "DROP TABLE events;", "/chat")
        assert status in ["hard_block", "soft_block"] or data["score"] > 0
        
        status, reason, data = detector.process_request("127.0.0.1", "SELECT * FROM users", "/chat")
        assert data["score"] > 0
    
    def test_xss_detection(self):
        """Test XSS attempt detection."""
        from app.services.abuse import AbuseDetector
        
        detector = AbuseDetector()
        
        status, reason, data = detector.process_request("127.0.0.1", "<script>alert(1)</script>", "/chat")
        assert data["score"] > 0
    
    def test_whitelisted_inputs(self):
        """Test that whitelisted inputs pass."""
        from app.services.abuse import AbuseDetector
        
        detector = AbuseDetector()
        
        whitelisted = ["hi", "hello", "thanks", "bye", "okay", "great"]
        
        for word in whitelisted:
            status, reason, data = detector.process_request("127.0.0.1", word, "/chat")
            assert status == "allowed"
    
    def test_normal_queries(self):
        """Test that normal queries pass."""
        from app.services.abuse import AbuseDetector
        
        detector = AbuseDetector()
        
        normal_queries = [
            "What events are happening today?",
            "Where is the hackathon?",
            "How do I register?",
            "Tell me about workshops",
        ]
        
        for query in normal_queries:
            status, reason, data = detector.process_request("127.0.0.1", query, "/chat")
            assert status == "allowed", f"Blocked: {query}"
    
    def test_ip_blocking(self):
        """Test IP blocking after threshold."""
        from app.services.abuse import AbuseDetector
        
        detector = AbuseDetector()
        
        ip = "192.168.1.100"
        
        # Simulate multiple violations
        for _ in range(10):
            detector.process_request(ip, "DROP TABLE events; DELETE FROM users;", "/chat")
        
        # Should be blocked now
        status, reason, data = detector.process_request(ip, "What events today?", "/chat")
        # Either blocked or high score
        assert status in ["hard_block", "soft_block"] or data["score"] >= 20


# =============================================================================
# CONVERSATION MANAGEMENT TESTS
# =============================================================================

class TestConversationManager:
    """Tests for conversation management."""
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_session(self):
        """Test creating a new session."""
        from app.services.conversation import ConversationManager
        
        manager = ConversationManager()
        
        context = await manager.get_or_create("session123")
        
        assert context.session_id == "session123"
        assert len(context.messages) == 0
        assert context.greeted is False
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_process_turn(self):
        """Test processing a conversation turn."""
        from app.services.conversation import ConversationManager
        
        manager = ConversationManager()
        
        context = await manager.process_turn(
            session_id="session123",
            user_query="What events are today?",
            assistant_response="There are 5 events today...",
            intent="schedule",
            confidence=0.9
        )
        
        assert len(context.messages) == 2
        assert context.messages[0].role == "user"
        assert context.messages[1].role == "assistant"
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_history_retrieval(self):
        """Test conversation history retrieval."""
        from app.services.conversation import ConversationManager
        
        manager = ConversationManager(max_history=5)
        
        # Add multiple turns
        for i in range(10):
            await manager.process_turn(
                session_id="session123",
                user_query=f"Query {i}",
                assistant_response=f"Response {i}"
            )
        
        context = await manager.get("session123")
        
        # Should be limited to max_history * 2
        assert len(context.messages) <= 10
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_greeted_flag(self):
        """Test greeted flag management."""
        from app.services.conversation import ConversationManager
        
        manager = ConversationManager()
        
        assert await manager.is_greeted("session123") is False
        
        await manager.mark_greeted("session123")
        
        assert await manager.is_greeted("session123") is True


class TestEntityExtractor:
    """Tests for entity extraction."""
    
    def test_date_extraction(self):
        """Test date entity extraction."""
        from app.services.conversation import EntityExtractor
        
        extractor = EntityExtractor()
        
        entities = extractor.extract("What events are today?")
        assert entities.get("date_reference") == "today"
        
        entities = extractor.extract("Show me tomorrow's schedule")
        assert entities.get("date_reference") == "tomorrow"
    
    def test_time_extraction(self):
        """Test time entity extraction."""
        from app.services.conversation import EntityExtractor
        
        extractor = EntityExtractor()
        
        entities = extractor.extract("What's happening at 3pm?")
        assert "time_reference" in entities
        
        entities = extractor.extract("Events in the morning")
        assert entities.get("time_reference") == "morning"
    
    def test_event_type_extraction(self):
        """Test event type extraction."""
        from app.services.conversation import EntityExtractor
        
        extractor = EntityExtractor()
        
        entities = extractor.extract("Tell me about the hackathon")
        assert entities.get("event_type") == "hackathon"
        
        entities = extractor.extract("List all workshops")
        assert entities.get("event_type") == "workshop"


# =============================================================================
# METRICS TESTS
# =============================================================================

class TestMetrics:
    """Tests for metrics service."""
    
    def test_counter_increment(self):
        """Test counter metric."""
        from prometheus_client import Counter
        
        # Create a fresh registry for testing to avoid duplicates
        from prometheus_client import CollectorRegistry
        registry = CollectorRegistry()
        
        counter = Counter("test_counter", "Test counter", registry=registry)
        
        counter.inc()
        counter.inc(5)
        
        assert registry.get_sample_value("test_counter_total") == 6
    
    def test_counter_with_labels(self):
        """Test counter with labels."""
        from prometheus_client import CollectorRegistry, Counter
        registry = CollectorRegistry()
        
        counter = Counter("test_labeled", "Test", ["method"], registry=registry)
        
        counter.labels(method="GET").inc()
        counter.labels(method="POST").inc(3)
        
        assert registry.get_sample_value("test_labeled_total", {"method": "GET"}) == 1
        assert registry.get_sample_value("test_labeled_total", {"method": "POST"}) == 3
    
    def test_gauge_operations(self):
        """Test gauge metric."""
        from prometheus_client import CollectorRegistry, Gauge
        registry = CollectorRegistry()
        
        gauge = Gauge("test_gauge", "Test gauge", registry=registry)
        
        gauge.set(10)
        assert registry.get_sample_value("test_gauge") == 10
        
        gauge.inc(5)
        assert registry.get_sample_value("test_gauge") == 15
        
        gauge.dec(3)
        assert registry.get_sample_value("test_gauge") == 12
    
    pass


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================

class TestSchemas:
    """Tests for Pydantic schemas."""
    
    def test_chat_request_valid(self):
        """Test valid chat request."""
        from app.api.schemas import ChatRequest
        
        request = ChatRequest(query="What events today?")
        assert request.query == "What events today?"
    
    def test_chat_request_validation(self):
        """Test chat request validation."""
        from app.api.schemas import ChatRequest
        
        # Empty query should fail
        with pytest.raises(ValueError):
            ChatRequest(query="")
        
        # Too long query should fail
        with pytest.raises(ValueError):
            ChatRequest(query="x" * 600)
    
    def test_chat_request_sanitization(self):
        """Test query sanitization."""
        from app.api.schemas import ChatRequest
        
        request = ChatRequest(query="  multiple   spaces  ")
        assert request.query == "multiple spaces"
    
    def test_feedback_request(self):
        """Test feedback request."""
        from app.api.schemas import FeedbackRequest, FeedbackType
        
        request = FeedbackRequest(
            interaction_id="abc123",
            feedback=FeedbackType.HELPFUL
        )
        assert request.feedback == FeedbackType.HELPFUL


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestHealthChecks:
    """Tests for health check service."""
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_health_registry(self):
        """Test health check registry."""
        from app.api.health import HealthCheckRegistry, ComponentHealth, HealthStatus
        
        registry = HealthCheckRegistry()
        
        async def healthy_check():
            return ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY
            )
        
        registry.register("test", healthy_check, critical=True)
        
        result = await registry.check_component("test")
        assert result.status == HealthStatus.HEALTHY
    
    @pytest.mark.asyncio(loop_scope="function")
    async def test_overall_health(self):
        """Test overall health calculation."""
        from app.api.health import HealthCheckRegistry, ComponentHealth, HealthStatus
        
        registry = HealthCheckRegistry()
        
        async def healthy():
            return ComponentHealth(name="healthy", status=HealthStatus.HEALTHY)
        
        async def unhealthy():
            return ComponentHealth(name="unhealthy", status=HealthStatus.UNHEALTHY)
        
        registry.register("healthy", healthy, critical=True)
        registry.register("unhealthy", unhealthy, critical=True)
        
        result = await registry.check_all()
        
        # Overall should be unhealthy if any critical component is unhealthy
        assert result.status == HealthStatus.UNHEALTHY


# =============================================================================
# LOGGING TESTS
# =============================================================================

class TestLogging:
    """Tests for logging service."""
    
    def test_sensitive_data_masking(self):
        """Test sensitive data masking."""
        from app.core.logging import SensitiveDataMasker
        
        masker = SensitiveDataMasker()
        
        # API key
        result = masker.mask("api_key=sk-abc123defghi456789012345")
        assert "***REDACTED***" in result
        assert "sk-abc" not in result

        
        # Password
        result = masker.mask('password: "mysecretpass"')
        assert "mysecretpass" not in result
        
        # Email
        result = masker.mask("user@example.com")
        assert "user" not in result
    
    def test_dict_masking(self):
        """Test dictionary masking."""
        from app.core.logging import SensitiveDataMasker
        
        masker = SensitiveDataMasker()
        
        data = {
            "username": "john",
            "password": "secret123",
            "api_key": "sk-12345"
        }
        
        result = masker.mask_dict(data)
        
        assert result["username"] == "john"
        assert "REDACTED" in result["password"]
        assert "REDACTED" in result["api_key"]


# =============================================================================
# RUN CONFIGURATION
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
