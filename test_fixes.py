import urllib.request
import json
import time
import sys

BASE_URL = "http://localhost:8000"

def call_api(endpoint, method="POST", data=None):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header('Content-Type', 'application/json')
    
    if data:
        json_data = json.dumps(data).encode('utf-8')
        req.data = json_data

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling {url}: {e}")
        return None

print("Triggering KB Refresh...")
res = call_api("/refresh", method="POST")
print(f"Refresh Response: {res}")

print("Waiting 45s for refresh to complete (fetching sheets + chunking)...")
time.sleep(45)

queries = [
    "who are you",
    "how to add team members",
    "hackaton",
    "hackathon"
]

for q in queries:
    print(f"\n--------------------------------------------------")
    print(f"Query: '{q}'")
    res = call_api("/chat", data={"query": q})
    if res:
        print(f"Answer: {res.get('answer', 'No answer')}")
        srcs = res.get('sources', [])
        print(f"Sources: {srcs}")
    else:
        print("Failed to get response.")
