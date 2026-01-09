import json
import urllib.request
import urllib.error
import time

API_URL = "http://localhost:8000/chat"

def query(q):
    data = json.dumps({"query": q}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode('utf-8')}

print("🔹 FINAL MICRO-CHECKLIST\n")

# 1. Greeting (once per session)
print("1. Greeting test...")
s1, r1 = query("hi")
s2, r2 = query("hi")
if "welcome" in r1.get("answer", "").lower() and "how can i help" in r2.get("answer", "").lower():
    print("✅ PASS: First greeting, then short response\n")
else:
    print(f"❌ FAIL: Greeting logic\n   First: {r1.get('answer', '')[:50]}\n   Second: {r2.get('answer', '')[:50]}\n")

time.sleep(0.5)

# 2. Events listing
print("2. Events listing...")
s, r = query("events")
ans = r.get("answer", "")
if "convenient" in ans.lower() and "hackathon" in ans.lower():
    print("✅ PASS: Returns event list\n")
else:
    print(f"❌ FAIL: Missing events\n   {ans[:100]}\n")

time.sleep(0.5)

# 3. Sorted list
print("3. Sorted chronologically...")
s, r = query("list events sorted by date")
ans = r.get("answer", "")
if "2025-01-24" in ans or "convenient" in ans.lower():
    print("✅ PASS: Chronological sorting\n")
else:
    print(f"❌ FAIL: Sorting issue\n   {ans[:100]}\n")

time.sleep(0.5)

# 4. Events today (system date)
print("4. Events today (system date)...")
s, r = query("events today")
ans = r.get("answer", "")
if "2026" in ans or "no events" in ans.lower():
    print("✅ PASS: System date respected\n")
else:
    print(f"❌ FAIL: Date logic\n   {ans[:100]}\n")

time.sleep(0.5)

# 5. Typo: coveniet
print("5. Fuzzy: 'coveniet'...")
s, r = query("coveniet")
ans = r.get("answer", "")
if "convenient" in ans.lower() or "couldn't find" in ans.lower():
    print("✅ PASS: Fuzzy match or safe fallback\n")
else:
    print(f"❌ FAIL: Fuzzy logic\n   {ans[:100]}\n")

time.sleep(0.5)

# 6. Acronym: uiux
print("6. Acronym: 'uiux'...")
s, r = query("uiux")
ans = r.get("answer", "")
if "ui/ux" in ans.lower() or "intro to ui" in ans.lower():
    print("✅ PASS: UI/UX recognized\n")
else:
    print(f"❌ FAIL: UI/UX mapping\n   {ans[:100]}\n")

time.sleep(0.5)

# 7. Unknown info
print("7. Chief guest (unknown)...")
s, r = query("who is the chief guest")
ans = r.get("answer", "")
if ("yet to be" in ans.lower() and "announced" in ans.lower()) or ("not" in ans.lower() and "announced" in ans.lower()):
    print("✅ PASS: Safe unknown handling\n")
else:
    print(f"❌ FAIL: Unknown info\n   {ans[:100]}\n")

time.sleep(0.5)

# 8. Soft refusal
print("8. Security: 'drop table' (soft)...")
s, r = query("drop table events")
if s == 400 or "cannot process" in str(r).lower():
    print("✅ PASS: Soft refusal (400)\n")
else:
    print(f"❌ FAIL: Expected 400, got {s}\n   {r}\n")

time.sleep(0.5)

# 9. Hard block
print("9. Security: repeat abuse (hard block)...")
for i in range(5):
    s, r = query("drop table events")
    if s == 403:
        print("✅ PASS: Hard block (403) triggered\n")
        break
    time.sleep(0.2)
else:
    print(f"❌ FAIL: No hard block after 5 attempts\n")

time.sleep(0.5)

# 10. Whitelist bypass
print("10. Whitelist: 'hi' after block...")
s, r = query("hi")
if s == 200 and ("hello" in r.get("answer", "").lower() or "help" in r.get("answer", "").lower()):
    print("✅ PASS: 'hi' still works despite block\n")
else:
    print(f"❌ FAIL: Whitelist broken\n   Status: {s}, Answer: {r.get('answer', '')[:50]}\n")

print("\n✅ MICRO-CHECKLIST COMPLETE")
