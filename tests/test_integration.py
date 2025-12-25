
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
from datetime import datetime

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sheets import SheetsService
from app.services.vector import VectorService

# ==========================================
# 1. Mock Google Sheets Integration
# ==========================================
@patch("app.services.sheets.gspread.authorize")
@patch("app.services.sheets.Credentials.from_service_account_file")
@patch("os.path.exists", return_value=True)
def test_sheets_fetch_events(mock_exists, mock_creds, mock_auth):
    """Test fetching events with mocked Sheets API"""
    
    # Mock Sheet Structure
    mock_client = MagicMock()
    mock_sheet = MagicMock()
    mock_worksheet_events = MagicMock()
    mock_worksheet_faq = MagicMock()
    
    # Setup Returns
    mock_auth.return_value = mock_client
    mock_client.open_by_key.return_value = mock_sheet
    mock_sheet.get_worksheet.side_effect = [mock_worksheet_events, mock_worksheet_faq]
    
    # Mock Data
    mock_worksheet_events.get_all_records.return_value = [
        {"Event Name": "Test Event", "Date": "2025-01-01", "Time": "10:00"}
    ]
    mock_worksheet_faq.get_all_records.return_value = [
        {"Question": "What is reliable?", "Answer": "This test suite."}
    ]
    
    # Run Service
    service = SheetsService()
    events = service.fetch_events()
    
    # Assertions
    assert len(events) == 2  # 1 event + 1 FAQ
    assert events[0]["event_name"] == "Test Event"
    assert events[1]["_is_faq"] is True
    assert events[1]["question"] == "What is reliable?"

# ==========================================
# 2. Mock ChromaDB Integration
# ==========================================
@pytest.mark.asyncio
async def test_vector_search_logic():
    """Test vector retrieval logic without real DB"""
    
    # Mock the embedding function and DB client
    with patch("app.services.vector.chromadb.PersistentClient") as MockClient:
        mock_collection = MagicMock()
        MockClient.return_value.get_collection.return_value = mock_collection
        
        # Init Service
        service = VectorService()
        # Force a collection to exist
        service.collection = mock_collection
        
        # Mock Query Results (Standard Chroma Response format)
        mock_collection.query.return_value = {
            "ids": [["doc1"]],
            "distances": [[0.1]],  # Low distance = High similarity
            "metadatas": [[{"type": "event"}]],
            "documents": [["Results for query"]]
        }
        
        # Test Search
        results = await service.search("test query")
        
        # Assertions
        assert len(results) == 1
        assert results[0]["id"] == "doc1"
        assert results[0]["score"] > 0.9  # 1.0 - (0.1/2) = 0.95
