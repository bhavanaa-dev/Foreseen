import os
import sys
import json
from pathlib import Path

# Add project root to import path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend import shopping

def main():
    query = "MacBook Air M1 8GB 256GB used"
    cache_dir = project_root / "cache"
    try:
        response = shopping.load_cached_response(cache_dir, query)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    results = response.get("shopping_results", [])
    total = len(results)
    unique, dup_cnt = shopping.deduplicate_items(results)
    # Classification counts
    counts = {"confirmed": 0, "ambiguous": 0, "mismatch": 0}
    multiple_sources = 0
    missing_price = 0
    for item in unique:
        cls = shopping.classify_item(item)
        counts[cls] += 1
        if item.get("multiple_sources"):
            multiple_sources += 1
        # price check: extracted_price must be present and positive int
        if not isinstance(item.get("extracted_price"), (int, float)):
            missing_price += 1
    print(f"Original result count: {total}")
    print(f"Exact duplicates removed: {dup_cnt}")
    print(f"Unique listings remaining: {len(unique)}")
    print(f"Confirmed matches: {counts['confirmed']}")
    print(f"Ambiguous listings: {counts['ambiguous']}")
    print(f"Mismatches: {counts['mismatch']}")
    print(f"Listings flagged as multiple sources: {multiple_sources}")
    print(f"Listings with missing or invalid price: {missing_price}")

if __name__ == "__main__":
    main()
