import asyncio
import aiohttp
import time
import random
import statistics
import json
from typing import List, Dict

# Configuration
BASE_URL = "http://159.89.161.81"
CONCURRENT_USERS = 100
RAMP_UP_SECONDS = 10
TOTAL_REQUESTS = 200  # 2 requests per user on average

# Diverse Queries Pool (from comprehensive test suite)
QUERIES = [
    "What workshops are available?",
    "When is the AI/ML workshop?",
    "Show me all hackathons",
    "What events are happening on January 25?",
    "List all events",
    "Tell me about CONVenient workshop",
    "What is VisionCraft?",
    "Details about Cassandra hackathon",
    "How do I register?",
    "When does registration open?",
    "Is registration free?",
    "Can I register for multiple events?",
    "What are the prerequisites for ML workshop?",
    "Do I need prior experience for VisionCraft?",
    "Where is Aurora Fest happening?",
    "What is the venue for workshops?",
    "How do I contact the organizers?",
    "Who can I reach out to for queries?",
    "What is Aurora Fest?",
    "Tell me about ISTE Manipal",
    "What is the theme of Aurora this year?", 
    "What ML workshops are there and when do they happen?",
    "Can you tell me about workshops for beginners?",
    "What worksops are availble?", # Typo
    "Wen is registraton?", # Typo
    "What AI/ML events r there?",
    "CV workshop details?",
    "When?",
    "How much?"
]

async def simulate_user(session: aiohttp.ClientSession, user_id: int):
    # Randomize start time (Ramp Up)
    delay = random.uniform(0, RAMP_UP_SECONDS)
    await asyncio.sleep(delay)
    
    # Pick random query
    query = random.choice(QUERIES)
    
    start_time = time.time()
    try:
        # Use stream=True logic implicitly by checking response headers or just measuring time to complete
        # For load testing, we just care about the POST request returning 200
        async with session.post(
            f"{BASE_URL}/chat",
            json={"query": query},
            timeout=aiohttp.ClientTimeout(total=45)
        ) as response:
            latency = time.time() - start_time
            
            # Read response (important to consume stream)
            response_text = await response.text()
            
            return {
                "user_id": user_id,
                "status": response.status,
                "latency": latency,
                "query": query,
                "error": None
            }
            
    except Exception as e:
        latency = time.time() - start_time
        return {
            "user_id": user_id,
            "status": 0,
            "latency": latency,
            "query": query,
            "error": str(e)
        }

async def run_stress_test():
    print(f"\n🚀 STARTING STRESS TEST")
    print(f"   Concurrent Users: {CONCURRENT_USERS}")
    print(f"   Ramp Up: {RAMP_UP_SECONDS}s")
    print(f"   Target URL: {BASE_URL}")
    print(f"   Query Pool: {len(QUERIES)} diverse questions")
    print("-" * 60)
    
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        # Create tasks
        tasks = [simulate_user(session, i) for i in range(CONCURRENT_USERS)]
        results = await asyncio.gather(*tasks)
        
    duration = time.time() - start_time
    
    # Analyze
    success = [r for r in results if r["status"] == 200]
    failed = [r for r in results if r["status"] != 200]
    latencies = [r["latency"] for r in success]
    
    print("\n📊 RESULTS")
    print(f"   Total Duration: {duration:.2f}s")
    print(f"   Throughput: {len(results)/duration:.1f} req/sec")
    print(f"   Success Rate: {len(success)}/{len(results)} ({len(success)/len(results)*100:.1f}%)")
    
    if latencies:
        print("\n⏱️  LATENCY Stats (seconds)")
        print(f"   Avg: {statistics.mean(latencies):.3f}s")
        print(f"   Med: {statistics.median(latencies):.3f}s")
        print(f"   Max: {max(latencies):.3f}s")
        print(f"   Min: {min(latencies):.3f}s")
        
    if failed:
        print("\n❌ FAILURES Breakdown")
        errors = {}
        for f in failed:
            err_msg = f"{f['status']} - {f['error']}"
            errors[err_msg] = errors.get(err_msg, 0) + 1
            
        for err, count in errors.items():
            print(f"   {count}x : {err}")

if __name__ == "__main__":
    asyncio.run(run_stress_test())
