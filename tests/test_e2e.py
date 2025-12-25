
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.api.routes import ChatRequest

# ==========================================
# 3. E2E Pipeline Test (Full App Boot)
# ==========================================
def test_full_pipeline_flow():
    """
    Boots the full FastAPI app and sends a request.
    Mocks ONLY the external LLM/DB calls to keep it fast/deterministic.
    Verifies routing, validation, middleware, and logic.
    """
    client = TestClient(app)
    
    # Mock external heavy services
    with patch("app.services.vector.VectorService.search", new_callable=MagicMock) as mock_search, \
         patch("app.services.llm.LLMService.get_answer", new_callable=MagicMock) as mock_llm, \
         patch("app.db.redis.RedisClient.get_history", new_callable=MagicMock) as mock_redis:
        
        # Setup Async Mock Returns
        mock_search.return_value = [{"text": "context", "score": 0.9}]
        mock_llm.return_value = {
            "answer": "Hello! I am Aurora Assistant.", 
            "confidence": 0.95,
            "used_docs": ["doc1"]
        }
        mock_redis.return_value = []  # No history
        
        # SEND REAL REQUEST
        response = client.post("/chat", json={"query": "Hi"})
        
        # Verify Response
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Hello! I am Aurora Assistant."
        assert data["confidence"] == 0.95
        assert data["tier"] == "High"
        
        # Verify Pipeline Steps
        # 1. Did it try to search vectors?
        mock_search.assert_called_once()
        # 2. Did it call LLM?
        mock_llm.assert_called_once()
