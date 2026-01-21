
import asyncio
import logging
from app.services.vector import get_vector_service
from app.services.sheets import get_sheets_service

# Configure logging
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        # Initialize services
        sheets = get_sheets_service() # Need sheets helper?
        vector = get_vector_service()
        
        # Manually trigger master list fetch
        # Note: Vector service init might be slow / async
        # But get_vector_service returns singleton
        
        # We need to wait for collection to be ready.
        # But the script imports app code which might init duplicate instance if not careful.
        # However, getting singleton is fine.
        
        # Since local script, we might not connect to same in-memory DB as running server!
        # AH. Redis/In-Memory fallback. 
        # If running server is in-memory, successful retrieval in script implies script creates NEW memory DB.
        # Which RE-INDEXES from Sheets.
        # So this verifies if "Re-Indexing" produces the tag.
        
        # Fetch events first (mock sync)
        # Actually vector service does init on startup.
        
        print("Wait for init...")
        await asyncio.sleep(5) 
        
        master = await vector.get_master_event_list()
        if master:
            print(f"\n--- MASTER LIST CONTENT ---\n{master['text']}\n---------------------------")
        else:
            print("Master list not found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
