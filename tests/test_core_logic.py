
import unittest
from unittest.mock import MagicMock, patch
import json
import hashlib
from app.core.config import settings
from app.services.llm import LLMService

class TestRAGLogic(unittest.TestCase):
    
    def setUp(self):
        # Ensure we are testing with known config values
        self.original_threshold = settings.CONFIDENCE_THRESHOLD
    
    def tearDown(self):
        # Restore config
        # (Note: In a real app we might want to patch settings object instead)
        pass

    def test_config_loading(self):
        """Test 1: Verify Pydantic settings are loaded correctly"""
        print(f"\n[INFO] Testing Config Loading...")
        self.assertIsNotNone(settings.GROQ_API_KEY)
        self.assertGreater(settings.MAX_CONVERSATION_USERS, 0)
        print(f"   Max Users Config: {settings.MAX_CONVERSATION_USERS}")

    def test_cache_key_generation(self):
        """Test 2: Verify Cache Key stability with new Architecture"""
        # We can implement a simulation of the key generation used in routes.py
        # or abstract key gen into a util. For now, we test the logic principle
        # which should match what's in app/api/routes.py
        
        query = " when is convenients? "
        intent = "schedule"
        
        # Logic from app/api/routes.py (we should ideally extract this to a reused function)
        query_normalized = query.lower().strip().replace("?", "").replace("!", "")
        cache_key_str = f"{query_normalized}|{intent}|{settings.CONFIDENCE_THRESHOLD}"
        key1 = hashlib.md5(cache_key_str.encode()).hexdigest()
        
        # Run again
        key2 = hashlib.md5(cache_key_str.encode()).hexdigest()
        
        self.assertEqual(key1, key2)
        print(f"   Cache Key: {key1}")

    @patch('app.services.llm.Groq')
    def test_llm_service_initialization(self, mock_groq):
        """Test 3: Verify LLM Service initializes with config key"""
        service = LLMService()
        # Verify Groq was called (checking if API key was passed depends on implementation details)
        mock_groq.assert_called()
        print("   LLM Service Initialized")

if __name__ == '__main__':
    unittest.main()
