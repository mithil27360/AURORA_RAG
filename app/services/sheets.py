
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
        """Authenticate and get client"""
        if not os.path.exists(settings.GOOGLE_CREDS_FILE):
            logger.warning(f"Credentials file not found at {settings.GOOGLE_CREDS_FILE}")
            return None
            
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_CREDS_FILE, scopes=self.scope
        )
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
