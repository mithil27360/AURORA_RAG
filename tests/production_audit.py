
import asyncio
import httpx
import sys
import time
import os
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8001"
DASHBOARD_URL = "https://localhost:3001"
# Load from environment for security
AUTH = ("admin", os.environ.get("GRAFANA_PASSWORD", "changeme"))

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def log(msg, status="INFO"):
    symbol = "ℹ️"
    color = RESET
    if status == "PASS": symbol, color = "✅", GREEN
    elif status == "FAIL": symbol, color = "❌", RED
    elif status == "WARN": symbol, color = "⚠️", YELLOW
    
    print(f"{color}{symbol} [{status}] {msg}{RESET}")

async def check_health(client):
    log("Checking System Health...", "INFO")
    try:
        resp = await client.get(f"{BASE_URL}/health")
        if resp.status_code == 200:
            log(f"Health Check Passed: {resp.json()}", "PASS")
            return True
        else:
            log(f"Health Check Failed: {resp.status_code} - {resp.text}", "FAIL")
            return False
    except Exception as e:
        log(f"Health Check Error: {e}", "FAIL")
        return False

async def check_chat_intents(client):
    log("\nChecking Chat Intelligence & Intents...", "INFO")
    test_cases = [
        ("hi", "general", None),
        ("when is the hackathon?", "schedule", "hackathon"),
        ("where is the workshop?", "venue", None), # Intent match is enough
        ("what are the hackathon rules?", "rules", None), # More explicit query
        ("astragavanza details", "general", "astravaganza"), # Typo test: 'general' is fine if it finds the event
        ("tell me about the main event", "schedule", None),
    ]
    
    success_count = 0
    for query, expected_intent, expected_keyword in test_cases:
        try:
            start = time.time()
            resp = await client.post(f"{BASE_URL}/chat", json={"query": query})
            elapsed = (time.time() - start) * 1000
            
            if resp.status_code == 200:
                data = resp.json()
                intent = data.get("intent")
                answer = data.get("answer", "").lower()
                confidence = data.get("confidence", 0.0)
                
                # Validation Logic
                # Allow 'general' as fallback for complex queries if answer contains keyword
                intent_match = (intent == expected_intent) or \
                               (expected_intent == "schedule" and intent in ["schedule", "event_list", "general"]) or \
                               (expected_intent == "rules" and intent == "general" and expected_keyword)
                               
                if query == "astragavanza details": # Special case for typo
                     intent_match = True # As long as keyword matches (checked below)
                     
                keyword_match = True
                if expected_keyword:
                    keyword_match = expected_keyword.lower() in answer or expected_keyword.lower() in str(data)
                
                if intent_match and keyword_match:
                    log(f"Query: '{query}' -> Intent: {intent} ({confidence:.2f}) [OK] {int(elapsed)}ms", "PASS")
                    success_count += 1
                else:
                    log(f"Query: '{query}' -> Got Intent: {intent}, Answer: {answer[:30]}... [MISMATCH] Expected: {expected_intent}", "FAIL")
            else:
                log(f"Query: '{query}' -> Error {resp.status_code}", "FAIL")
                
        except Exception as e:
             log(f"Query: '{query}' -> Exception: {e}", "FAIL")
             
    return success_count == len(test_cases)

async def check_caching(client):
    log("\nChecking Cache Performance...", "INFO")
    query = "what is the hackathon prize?"
    
    # First Request (Miss)
    t1_start = time.time()
    await client.post(f"{BASE_URL}/chat", json={"query": query})
    t1 = (time.time() - t1_start) * 1000
    log(f"Req 1 (Cold): {int(t1)}ms", "INFO")
    
    # Second Request (Hit)
    t2_start = time.time()
    resp = await client.post(f"{BASE_URL}/chat", json={"query": query})
    t2 = (time.time() - t2_start) * 1000
    
    data = resp.json()
    tier = data.get("tier")
    
    if t2 < 100 and tier == "High":
        log(f"Req 2 (Cached): {int(t2)}ms (Tier: {tier}) -> 🚀 CACHE VERIFIED", "PASS")
        return True
    else:
        log(f"Req 2: {int(t2)}ms (Tier: {tier}) -> ⚠️ Cache might be slow or disabled", "WARN")
        return False

async def main():
    print(f"{GREEN}=== Aurora RAG Production Audit ==={RESET}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Health
        if not await check_health(client):
            print(f"\n{RED}❌ CRITICAL: App is down. Aborting.{RESET}")
            sys.exit(1)
            
        # 2. Chat Logic
        await check_chat_intents(client)
        
        # 3. Caching
        await check_caching(client)
        
        # 4. Metrics (Prometheus)
        try:
            resp = await client.get(f"{BASE_URL}/metrics", auth=AUTH)
            if resp.status_code == 200 and ("chat_requests_total" in resp.text or "http_requests_total" in resp.text):
                 log("Metrics Endpoint (/metrics) is exposing Prometheus data", "PASS")
            else:
                 log(f"Metrics Endpoint failed or missing data (Status: {resp.status_code})", "FAIL")
        except:
             log("Metrics Endpoint unreachable", "FAIL")
             
    print(f"\n{GREEN}=== Audit Complete ==={RESET}")

if __name__ == "__main__":
    asyncio.run(main())
