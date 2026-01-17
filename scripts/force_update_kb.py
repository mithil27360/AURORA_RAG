import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.services.sheets import get_sheets_service
from app.services.vector import get_vector_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def force_update():
    logger.info("Starting force update of Knowledge Base...")
    sheets = get_sheets_service()
    vector = get_vector_service()
    
    try:
        logger.info("Fetching events from Sheets...")
        events = await asyncio.to_thread(sheets.fetch_events)
        logger.info(f"Fetched {len(events)} events from Sheets")
        
        logger.info("Updating Vector DB...")
        await vector.update_kb(events, force=True)
        logger.info("Force update complete.")
    except Exception as e:
        logger.error(f"Update failed: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(force_update())
