
import sys
import os
import requests
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def check_service(name, url, auth=None, expected_code=200):
    try:
        if auth:
            response = requests.get(url, auth=auth, verify=False, timeout=5)
        else:
            response = requests.get(url, verify=False, timeout=5)
        
        if response.status_code == expected_code:
            print(f"✅ {name}: UP ({url})")
            return True
        else:
            print(f"❌ {name}: DOWN (Status {response.status_code})")
            return False
    except Exception as e:
        print(f"❌ {name}: DOWN ({str(e)})")
        return False

def check_chat():
    print("\n💬 Testing Chatbot Logic...")
    queries = [
        ("Greetings", "hi"),
        ("Vector Search", "where is the hackathon?"),
        ("General", "what is this event?")
    ]
    
    all_passed = True
    for intent, query in queries:
        try:
            start = time.time()
            res = requests.post("http://localhost:8000/chat", json={"query": query}, timeout=10).json()
            duration = (time.time() - start) * 1000
            
            if "answer" in res:
                print(f"  ✅ {intent}: Success ({int(duration)}ms) - Answer: {res['answer'][:30]}...")
            else:
                print(f"  ❌ {intent}: Failed - {res}")
                all_passed = False
        except Exception as e:
            print(f"  ❌ {intent}: Error - {e}")
            all_passed = False
            
    return all_passed

def check_monitoring():
    print("\n📊 Checking Monitoring Data...")
    try:
        auth = ('admin', os.environ.get('PROMETHEUS_PASSWORD', 'changeme'))
        
        # Check targets
        targets = requests.get("http://localhost:9090/api/v1/targets", auth=auth).json()
        active = targets['data']['activeTargets']
        print(f"  found {len(active)} targets")
        for t in active:
            state = t['health'].upper()
            symbol = "✅" if state == 'UP' else "❌"
            print(f"  {symbol} Target {t['labels']['job']}: {state}")

        # Check metrics match
        query = requests.get("http://localhost:9090/api/v1/query", params={'query': 'chat_requests_total'}, auth=auth).json()
        series = len(query['data']['result'])
        print(f"  ✅ Prometheus has {series} chat metric series recorded")
        
    except Exception as e:
        print(f"  ❌ Monitoring Check Failed: {e}")

print("🚀 STARTING FULL SYSTEM VERIFICATION\n")

# 1. Check access
if not check_service("Chatbot API", "http://localhost:8000/health"): sys.exit(1)
check_service("Prometheus", "http://localhost:9090/-/healthy") # auth handled in monitoring check usually, or public health
check_service("Grafana", "https://localhost:3001/api/health")

# 2. Check Chat Functionality
check_chat()

# 3. Check Monitoring Stack
check_monitoring()

print("\n✨ Verification Complete")
