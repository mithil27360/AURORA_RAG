import re
import difflib

def fuzzy_search_debug(query, text):
    # Regex to find "1. Name (Type)" -> Capture Name
    pattern = r"\d+\.\s+(.*?)\s+\("
    event_names = re.findall(pattern, text)
    print(f"Extracted Names: {event_names}")
    
    # 1. Normalize query for substring check
    query_alnum = re.sub(r'[^a-z0-9]', '', query.lower())
    print(f"Query Alnum: '{query_alnum}'")
    
    found = set()
    
    for name in event_names:
        # Normalize name: "Intro to UI/UX" -> "introtouiux"
        name_alnum = re.sub(r'[^a-z0-9]', '', name.lower())
        # print(f"  Check '{query_alnum}' in '{name_alnum}'?")
        if len(query_alnum) > 3 and query_alnum in name_alnum:
            print(f"  MATCH: {name}")
            found.add(name)

    # 2. Existing Difflib (Whole Query)
    matches = difflib.get_close_matches(query, event_names, n=1, cutoff=0.6)
    if matches:
        print(f"  DIFFLIB MATCH: {matches[0]}")
        found.add(matches[0])

    return list(found)

test_text = """
1. CONVenient (Workshop) - by ACM, Manipal (2025-01-24)
2. Fusion 3C0 Generative Design Workshop (Workshop) - by DronAid (2025-01-24)
3. VisionCraft: Mastering Computer Vision (Workshop) - by ACM-W, Manipal (2025-01-24)
4. Intro to UI/UX: Designing Wireframes and Prototypes (Workshop) - by LeanIn, Manipal (2025-01-24)
"""

print("Testing 'uiux':", fuzzy_search_debug("uiux", test_text))
