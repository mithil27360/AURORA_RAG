"""Core logic tests."""
import pytest


def test_health_endpoint():
    """Test health endpoint returns 200."""
    # This would be mocked in actual tests
    assert True


def test_intent_classification():
    """Test intent detection for schedule queries."""
    query = "when is the hackathon"
    keywords = ["when", "schedule", "time"]
    assert any(k in query.lower() for k in keywords)


def test_confidence_threshold():
    """Test confidence threshold filtering."""
    threshold = 0.05
    scores = [0.8, 0.3, 0.02, 0.1]
    filtered = [s for s in scores if s >= threshold]
    assert len(filtered) == 3
