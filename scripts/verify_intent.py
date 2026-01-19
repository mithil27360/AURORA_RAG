import re

def check_intent(query):
    query_lower = query.lower().strip()
    
    if re.search(r'\b(hi|hello|hey|greetings|good\s+morning|good\s+evening)\b', query_lower):
        return "greeting"
    elif re.search(r'\b(hmm|ok|okay|cool|nice|thanks|thank\s+you|great|bye|goodbye)\b', query_lower):
        return "small_talk"
    return "general"

test_cases = [
    ("hi", "greeting"),
    ("hi there", "greeting"),
    ("hello bot", "greeting"),
    ("good morning everyone", "greeting"),
    ("okay", "small_talk"),
    ("okay thanks", "small_talk"),
    ("bye now", "small_talk"),
    ("this is cool", "small_talk"), # Might be false positive? "cool" is broad.
    ("the hill", "general"), # Should NOT match "hi"
    ("highway", "general"),   # Should NOT match "hi"
    ("book", "general")       # Should NOT match "ok"
]

failed = False
for q, expected in test_cases:
    result = check_intent(q)
    status = "PASS" if result == expected else "FAIL"
    print(f"[{status}] '{q}' -> {result} (Expected: {expected})")
    if result != expected:
        failed = True

if failed:
    print("\nSome tests failed!")
else:
    print("\nAll tests passed!")
