import asyncio
import logging
import sys
import os
import re

# Add project root to path
sys.path.append(os.getcwd())

from app.services.vector import get_vector_service

logging.basicConfig(level=logging.ERROR)

async def test_search():
    vector = get_vector_service()
    
    # DEBUG: Fetch Master List
    print("Fetching Master List...")
    master = await vector.get_master_event_list()
    if master:
        text = master.get("text", "")
        print(f"Master List Length: {len(text)} chars")
        print("--- Master List Preview (First 500 chars) ---")
        print(text[:500])
        print("--- Master List Preview (Last 500 chars) ---")
        print(text[-500:])
        print("-------------------------------------------")
        
        # Test Regex on this text
        pattern = r"\d+\.\s+(.*?)\s+\(.*\)\s+-\s+by\s+(.*?)\s+\(?\d"
        matches = re.findall(pattern, text)
        print(f"Regex Matches in Live Data: {len(matches)}")
        if matches:
            print(f"Sample Match: {matches[0]}")
    else:
        print("MASTER LIST NOT FOUND!")

    queries = [
        "whats the venue for AWS workshop",
        "when is the ADG workshop",
        "whats proze pool"
    ]
    
    for query in queries:
        print(f"\nQUERY: '{query}'")
        fuzzy = await vector.fuzzy_search_event(query)
        print(f"  -> Fuzzy Matches: {fuzzy}")
        
        # results = await vector.search(query, k=3)
        # ... skips search for brevity ...

if __name__ == "__main__":
    asyncio.run(test_search())
