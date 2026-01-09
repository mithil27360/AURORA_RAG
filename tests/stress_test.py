import json
import time
import sys
import urllib.request
import urllib.error

# Configuration
API_URL = "http://localhost:8000/chat"
DELAY = 0.5  # Delay between requests to avoid rate limits (unless testing them)

def send_query(query, expected_status=200):
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json"})
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            response_data = json.loads(body)
            # print(f"[{status}] Q: '{query}' -> A: {response_data.get('answer', 'No Answer')} (Confidence: {response_data.get('confidence')})")
            return status, response_data
    except urllib.error.HTTPError as e:
        # print(f"[{e.code}] Q: '{query}' -> Error: {e.read().decode('utf-8')}")
        return e.code, {"detail": e.read().decode('utf-8')}
    except Exception as e:
        print(f"[FAIL] Q: '{query}' -> Exception: {e}")
        return 0, str(e)

def run_section(name, tests):
    print(f"\n🔹 {name}")
    passed = 0
    for t in tests:
        q = t["q"]
        expected_substrings = t.get("expect", [])
        expected_code = t.get("code", 200)
        forbidden_substrings = t.get("bid", []) # Forbid these strings
        
        status, res = send_query(q)
        
        # Check Status
        if status != expected_code:
            print(f"❌ FAIL: '{q}' | Expected {expected_code}, got {status}")
            print(f"   Response: {res}")
            continue

        # Check Content
        res_text = json.dumps(res).lower()
        success = True
        
        for exp in expected_substrings:
            if exp.lower() not in res_text:
                print(f"❌ FAIL: '{q}' | Missing '{exp}'")
                print(f"   Response: {res}")
                success = False
                break
        
        for bid in forbidden_substrings:
            if bid.lower() in res_text:
                print(f"❌ FAIL: '{q}' | Found Forbidden '{bid}'")
                print(f"   Response: {res}")
                success = False
                break
                
        if success:
            print(f"✅ PASS: '{q}'")
            passed += 1
        time.sleep(DELAY)
    return passed

# Define Tests
sections = [
    ("A. BASIC SANITY", [
        {"q": "hi", "expect": ["hello", "welcome"]},
        {"q": "hi", "expect": ["how can i help"]}, # Second time -> Short
        {"q": "thanks", "expect": ["welcome"]},
        {"q": "bye", "expect": ["goodbye", "bye"]},
    ]),
    ("B. EVENT LISTING", [
        {"q": "list all events", "expect": ["convenient", "hackathon", "visioncraft", "12 events"]},
        {"q": "show events", "expect": ["convenient"]},
    ]),
    ("C. SORT & COUNT", [
        {"q": "how many events are there", "expect": ["12"]},
        {"q": "list events sorted by date", "expect": ["2025-01-24"]}, # Should start with early date
    ]),
    ("D. EVENT SPECIFIC", [
        {"q": "when is the hackathon", "expect": ["2055-01-26", "2055-01-28", "error 456"]}, # Data says 2055? Checking system truth.
        {"q": "convenient schedule", "expect": ["2025-01-24", "17:30"]},
        {"q": "visioncraft venue", "expect": ["ml lab"]},
    ]),
    ("E. FUZZY / TYPO", [
        {"q": "there is coveniet event", "expect": ["convenient"]},
        {"q": "vision craft", "expect": ["visioncraft"]},
        {"q": "uiux", "expect": ["ui/ux"]},
    ]),
    ("F. DATE LOGIC", [
        {"q": "what is todays date", "expect": ["2026"]}, # System date
        {"q": "events today", "expect": ["no events", "2026"]},
    ]),
    ("G. METADATA", [
        {"q": "who is organizing visioncraft", "expect": ["acm-w"]},
    ]),
    ("H. UNKNOWN INFO", [
        {"q": "who is the chief guest", "expect": ["yet to be", "announced"]},
        {"q": "who funded aurora fest", "expect": ["couldn't find", "specific details"]}, # Generic fallback
    ]),
    ("I. NONSENSE", [
        {"q": "asdjklqweoiu", "expect": ["didn't quite catch", "rephrase"]},
        {"q": "🐍🔥💀", "expect": ["didn't quite catch"]},
    ]),
    ("J. PROFANITY (Soft)", [
        {"q": "this bot is stupid", "expect": ["professional", "can't process"], "code": 400},
    ]),
    ("L. FILE ATTACKS", [
        {"q": "<script>alert(1)</script>", "expect": ["can't process"], "code": 400},
        {"q": "../../etc/passwd", "expect": ["can't process"], "code": 400},
    ]),
    ("M. CONTEXT CARRY", [
        {"q": "hackathon", "expect": ["error 456"]},
        {"q": "venue", "expect": ["library"]}, # Context from previous q
    ]),
]

def run_block_tests():
    print(f"\n🔹 K. SECURITY & BLOCKING (Destructive)")
    
    # 1. Soft Refusal (One-off abuse)
    run_section("K1. SQL Injection (Soft)", [
        {"q": "drop table events;", "expect": ["can't process"], "code": 400}
    ])
    
    # 2. Hard Block (Repeat Attack)
    print("   Running Repeat Attack (5x)...")
    for i in range(5):
        s, r = send_query("drop table events;")
        print(f"   Attempt {i+1}: {s}")
        if s == 403:
            print("   ✅ Blocked (403) received.")
            break
        time.sleep(0.2)
    
    # 3. Post-Block Whitelist
    print("   Verifying Whitelist Bypass...")
    s, r = send_query("hi")
    if s == 200 and ("hello" in json.dumps(r).lower() or "help" in json.dumps(r).lower()):
        print("✅ PASS: 'hi' worked despite block.")
    else:
        print(f"❌ FAIL: 'hi' blocked or failed. Status: {s}, Body: {r}")

if __name__ == "__main__":
    for name, tests in sections:
        run_section(name, tests)
    
    run_block_tests()
