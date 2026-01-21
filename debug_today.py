
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_query(q):
    print(f"\n--- Query: '{q}' ---")
    try:
        resp = requests.post(f"{BASE_URL}/chat", json={"query": q, "threshold": 0.5})
        data = resp.json()
        print(f"Answer: {data.get('answer')}")
        print(f"Sources: {data.get('sources')}")
        print(f"Intent: {data.get('intent')}")
        print(f"Cached: {data.get('cached')}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_query("WHATS TODAYS EVENTS")
