import requests
import time
import json
import sys

def test_latency(url="http://159.89.161.81/chat", query="What is Aurora?"):
    print(f"Testing Latency for: '{query}'")
    print(f"Target URL: {url}")
    
    start_time = time.time()
    ttfb = 0
    total_time = 0
    
    try:
        # Use stream=True to measure TTFB for streaming responses
        with requests.post(url, json={"query": query}, stream=True, timeout=10) as response:
            if response.status_code != 200:
                print(f"❌ Failed: HTTP {response.status_code}")
                return
            
            # Read first byte/chunk
            first_chunk = next(response.iter_content(chunk_size=10), None)
            ttfb = time.time() - start_time
            print(f"⏱️  Time To First Byte (TTFB): {ttfb*1000:.2f} ms")
            
            # Read rest
            content = b""
            if first_chunk:
                content += first_chunk
                for chunk in response.iter_content(chunk_size=1024):
                    content += chunk
            
            total_time = time.time() - start_time
            print(f"⏱️  Total Duration: {total_time*1000:.2f} ms")
            
            if ttfb < 2.0:
                print("✅ LATENCY TARGET MET (<2s)")
            else:
                print("❌ LATENCY TARGET MISSED (>2s)")
                
            print(f"Response: {content.decode('utf-8')[:100]}...")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "When is the AI workshop?"
    test_latency(query=query)
