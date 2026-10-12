import json
import pathlib
from pathlib import Path

# Add project root to sys.path
import sys, os
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

from backend.price_estimator import _load_cached_response, _numeric_price, estimate_price
from backend.shopping import classify_item, deduplicate_items

cache_dir = Path.cwd() / "cache"
payload = _load_cached_response(cache_dir)
if not payload:
    print('No cached response')
    sys.exit(0)
results = payload.get('response', {}).get('shopping_results', [])
unique_items, dup_count = deduplicate_items(results)

confirmed = []
ambiguous = []
mismatches = []

for item in unique_items:
    classification = classify_item(item)
    # promotion rule
    if item.get('multiple_sources') and classification != 'mismatch':
        promotion = True
        classification = 'confirmed'
    else:
        promotion = False
    item['_original_classification'] = classification  # store final classification
    item['_promotion'] = promotion
    if classification == 'confirmed':
        confirmed.append(item)
    elif classification == 'ambiguous':
        ambiguous.append(item)
    else:
        mismatches.append(item)

print('=== Confirmed listings (final classification) ===')
for i, it in enumerate(confirmed, 1):
    print(f"{i}. Title: {it.get('title')}")
    print(f"   Price: {_numeric_price(it)}")
    print(f"   Source: {it.get('source')}")
    print(f"   URL: {it.get('product_link')}")
    print(f"   Condition: {it.get('second_hand_condition')}")
    print(f"   Rating: {it.get('rating')}, Reviews: {it.get('review_count')}")
    print(f"   Multiple sources: {it.get('multiple_sources')}")
    print(f"   Promotion applied: {it.get('_promotion')}")
    print(f"   Original classification (pre-promotion): {it.get('_original_classification')}")
    print()

# Recalculate stats using confirmed prices
prices = [_numeric_price(it) for it in confirmed]
prices = [p for p in prices if p is not None]
print('Prices used for stats:', prices)
if prices:
    from statistics import median
    sorted_prices = sorted(prices)
    cnt = len(sorted_prices)
    min_price = sorted_prices[0]
    max_price = sorted_prices[-1]
    med = median(sorted_prices)
    # quartile calculation as in estimator
    def quartiles(vals):
        n = len(vals)
        q1_pos = int((0.25 * n + 0.5))
        q3_pos = int((0.75 * n + 0.5))
        q1_idx = max(0, min(n - 1, q1_pos - 1))
        q3_idx = max(0, min(n - 1, q3_pos - 1))
        return vals[q1_idx], vals[q3_idx]
    q1, q3 = quartiles(sorted_prices)
    spread = max_price - min_price
    confidence = 'low' if cnt < 5 else 'high'
    print('\n=== Recalculated statistics ===')
    print(f"Count: {cnt}")
    print(f"Sorted prices: {sorted_prices}")
    print(f"Min: {min_price}, Max: {max_price}")
    print(f"Median: {med}")
    print(f"Q1: {q1}, Q3: {q3}")
    print(f"Spread: {spread}")
    print(f"Confidence: {confidence}")
else:
    print('No confirmed prices')
