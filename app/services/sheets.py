
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
            
            # Iterate worksheets to find the right ones
            all_ws = sheet.worksheets()
            event_ws = None
            faq_ws = None
            
            for ws in all_ws:
                title = ws.title.lower().strip()
                if "event" in title: # Matches "event details", "events", "event_details"
                    event_ws = ws
                elif "faq" in title: # Matches "fully faq", "faqs"
                    faq_ws = ws
            
            # Fallback to index if names fail (Safety net)
            if not event_ws:
                logger.warning("Could not find sheet with 'event' in title. Defaulting to first sheet.")
                event_ws = all_ws[0]
            
            logger.info(f"Using Event Sheet: '{event_ws.title}'")
            
            # Fetch Events
            data = event_ws.get_all_records()
            
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
            
            # Fetch FAQs
            if faq_ws:
                logger.info(f"Using FAQ Sheet: '{faq_ws.title}'")
                try:
                    faq_data = faq_ws.get_all_records()
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
            else:
                logger.warning("No FAQ sheet found (checked for 'faq' in title).")
            
            return normalized_data

        except Exception as e:
            logger.error(f"Error fetching from Sheets: {e}")
            raise e

sheets_service = SheetsService()

def get_sheets_service():
    return sheets_service
