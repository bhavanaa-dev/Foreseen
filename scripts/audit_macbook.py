import json, re, pathlib, sys
path = r'C:\Users\HP\Documents\Foreseen\cache\google_shopping_MacBook_Air_M1_8GB_256GB_used_20261012T050233Z.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
results = data['response']['shopping_results']

def evidence(title):
    low = title.lower()
    has_m1 = bool(re.search(r'\bm1\b', low))
    has_8gb = bool(re.search(r'8\s*gb', low))
    has_256gb = bool(re.search(r'256\s*gb', low))
    return has_m1, has_8gb, has_256gb

def classify(rec):
    title = rec.get('title','')
    low = title.lower()
    if 'intel' in low or 'core i' in low:
        return 'Intel'
    if 'macbook pro' in low:
        return 'MacBook Pro'
    has_m1, has_8, has_256 = evidence(title)
    if has_m1 and has_8 and has_256:
        return 'Exact-Spec'
    if 'macbook' in low:
        return 'Ambiguous'
    return 'Non-Apple'

rows = []
for rec in results:
    cls = classify(rec)
    if cls == 'Non-Apple':
        continue
    title = rec.get('title','')
    price = rec.get('extracted_price')
    source = rec.get('source','')
    link = rec.get('product_link','')
    condition = rec.get('second_hand_condition','')
    rating = rec.get('rating')
    reviews = rec.get('reviews')
    mult = rec.get('multiple_sources','')
    has_m1, has_8, has_256 = evidence(title)
    evidence_str = []
    if has_m1: evidence_str.append('M1')
    if has_8: evidence_str.append('8GB')
    if has_256: evidence_str.append('256GB')
    if not evidence_str:
        evidence_str = ['none']
    rows.append({
        'pos': rec.get('position'),
        'title': title,
        'price': price,
        'source': source,
        'link': link,
        'condition': condition,
        'rating': rating,
        'reviews': reviews,
        'multiple_sources': mult,
        'evidence': ','.join(evidence_str),
        'class': cls
    })
    if len(rows) >= 20:
        break

# Print markdown table
print('|Pos|Title|Price|Source|Link|Evidence|Class|Cond|Rating|Reviews|MultiSrc|')
print('|---|-----|-----|------|----|--------|-----|----|------|-------|--------|')
for r in rows:
    print(f"|{r['pos']}|{r['title']}|{r['price']}|{r['source']}|{r['link']}|{r['evidence']}|{r['class']}|{r['condition']}|{r['rating']}|{r['reviews']}|{r.get('multiple_sources','')}|")
