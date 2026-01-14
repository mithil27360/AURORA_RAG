import asyncio
import httpx
import time
import sys

# Configuration
URL = "http://159.89.161.81/chat"
CONCURRENT_USERS = 50
TIMEOUT = 30.0

async def simulate_user(client, user_idx):
    # Simulate realistic arrival (Ramp Up)
    # 50 users over 15 seconds = ~3.3 users/sec arrival rate
    delay = (user_idx / CONCURRENT_USERS) * 15.0
    await asyncio.sleep(delay)
    
    start_time = time.time()
    try:
        # Unique session for each user to test rate limiting per-user tracking logic
        # But rate limit is usually IP based in basic setup unless using session_id
        # Middleware uses: key_func=get_remote_address usually.
        # If IP rate limit, 50 requests from my IP might trigger it!
        # Limit is 60/min. So 50 should pass.
        
        payload = {
            "query": "When is the hackathon?", 
            "session_id": f"load_tester_{user_idx}"
        }
        
        response = await client.post(URL, json=payload, timeout=TIMEOUT)
        duration = time.time() - start_time
        return {
            "status": response.status_code,
            "latency": duration,
            "error": None
        }
    except Exception as e:
        duration = time.time() - start_time
        return {
            "status": 0,
            "latency": duration,
            "error": str(e)
        }

async def main():
    print(f"🚀 Starting load test: {CONCURRENT_USERS} users hitting {URL}...")
    
    async with httpx.AsyncClient() as client:
        tasks = [simulate_user(client, i) for i in range(CONCURRENT_USERS)]
        results = await asyncio.gather(*tasks)

    # Analysis
    success = [r for r in results if r["status"] == 200]
    rate_limited = [r for r in results if r["status"] == 429]
    failed = [r for r in results if r["status"] not in (200, 429)]
    
    print("\n📊 Load Test Results")
    print("====================")
    print(f"Total Requests: {len(results)}")
    print(f"✅ Success 200: {len(success)}")
    print(f"🛑 Rate Limit 429: {len(rate_limited)}")
    print(f"❌ Failed Other: {len(failed)}")
    
    if success:
        total_lat = sum(r['latency'] for r in success)
        avg_lat = total_lat / len(success)
        max_lat = max(r['latency'] for r in success)
        min_lat = min(r['latency'] for r in success)
        print(f"\n⏱️ Latency (Success)")
        print(f"   Avg: {avg_lat:.2f}s")
        print(f"   Min: {min_lat:.2f}s")
        print(f"   Max: {max_lat:.2f}s")

    if failed:
        print(f"\n⚠️ Errors:")
        for r in failed[:5]:
            print(f"   - Status {r['status']}: {r['error']}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
