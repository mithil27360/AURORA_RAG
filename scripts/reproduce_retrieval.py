import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.vector import VectorService
from app.api.routes import normalize_query

async def main():
    print("Initializing Vector Service...")
    service = VectorService()
    
    query = "festival guide"
    print(f"\nQuery: '{query}'")
    
    # 1. Check Normalization
    norm = normalize_query(query)
    print(f"Normalized: '{norm}'")
    
    # 2. Check Intent Classification (simulate what routes.py does)
    query_lower = query.lower()
    intent = "general"
    if any(x in query_lower for x in ["schedule", "when", "time", "date", "calendar", "event", "events", "clash", "conflict", "overlap"]):
        intent = "schedule"
    elif any(x in query_lower for x in ["where", "venue", "location", "place", "room"]):
        intent = "venue"
    
    print(f"Calculated Intent: {intent}")
    
    # 3. Perform Search
    print("\nPerforming Vector Search...")
    results = await service.search(query, k=5)
    
    print(f"\nFound {len(results)} chunks:")
    for i, res in enumerate(results):
        print(f"[{i+1}] ID: {res['id']} (Score: {res['score']:.4f})")
        print(f"    Type: {res['meta'].get('type')}")
        print(f"    Excerpt: {res['text'][:100]}...")
        
    # 4. Check if master_event_list is present
    has_master = any(r['id'] == 'master_event_list' for r in results)
    print(f"\nMaster Event List Found: {has_master}")

if __name__ == "__main__":
    asyncio.run(main())
