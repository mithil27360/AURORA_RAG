
import os
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict
from app.core.config import settings

logger = logging.getLogger(__name__)

class SheetsService:
    def __init__(self):
        self.scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
    def _get_client(self):
        """Authenticate using file or env var (for Render deployment)."""
        creds = None
        
        # Option 1: JSON from environment variable (Render)
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if creds_json:
            try:
                creds_data = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_data, scopes=self.scope)
                logger.info("Using credentials from GOOGLE_CREDS_JSON env var")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid GOOGLE_CREDS_JSON: {e}")
        
        # Option 2: File path (local/Docker)
        if not creds and os.path.exists(settings.GOOGLE_CREDS_FILE):
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDS_FILE, scopes=self.scope
            )
            logger.info(f"Using credentials from file: {settings.GOOGLE_CREDS_FILE}")
        
        if not creds:
            logger.warning("No Google credentials found (file or env var)")
            return None
            
        return gspread.authorize(creds)

    def fetch_events(self) -> List[Dict]:
        """Fetch all events from Google Sheets"""
        client = self._get_client()
        if not client:
            return []

        try:
            sheet = client.open_by_key(settings.GOOGLE_SHEETS_ID)
            
            # Fetch Events (Worksheet 0)
            worksheet = sheet.get_worksheet(0)
            data = worksheet.get_all_records()
            
            # Normalize keys to lowercase/underscore
            normalized_data = []
            for row in data:
                # Basic cleaning
                clean_row = {
                    k.lower().strip().replace(" ", "_"): str(v).strip() 
                    for k, v in row.items() 
                    if k and str(v).strip()
                }
                if "event_name" in clean_row:
                    normalized_data.append(clean_row)
            
            logger.info(f"Fetched {len(normalized_data)} raw events from Sheets")
            
            # Fetch FAQs (Worksheet 1) if exists
            try:
                faq_sheet = sheet.get_worksheet(1)
                faq_data = faq_sheet.get_all_records()
                for row in faq_data:
                    clean_row = {
                        k.lower().strip().replace(" ", "_"): str(v).strip() 
                        for k, v in row.items() 
                        if k and str(v).strip()
                    }
                    if "question" in clean_row and "answer" in clean_row:
                        clean_row["_is_faq"] = True
                        normalized_data.append(clean_row)
                logger.info(f"Fetched {len(faq_data)} FAQs from Sheets")
            except Exception as faq_e:
                logger.warning(f"Could not fetch FAQs: {faq_e}")
            
            return normalized_data

        except Exception as e:
            logger.error(f"Error fetching from Sheets: {e}")
            raise e

sheets_service = SheetsService()

def get_sheets_service():
    return sheets_service
