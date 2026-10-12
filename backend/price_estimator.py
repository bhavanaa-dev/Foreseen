import json
import os
from pathlib import Path
from statistics import median
from typing import List, Dict, Any, Tuple, Optional

# Re‑use the shopping module (collection, classification, cache helpers).
# Support being imported both as ``backend.price_estimator`` (tests/package)
# and as a top‑level ``price_estimator`` (Flask app) so that monkeypatching
# ``shopping`` in tests affects the running app.
try:
    from backend import shopping
except ImportError:  # pragma: no cover - import style fallback
    try:
        from . import shopping
    except ImportError:
        import shopping

build_spec = shopping.build_spec
classify_item = shopping.classify_item
deduplicate_items = shopping.deduplicate_items

DEFAULT_CACHE_DIR = Path.cwd() / "cache"
MIN_ELIGIBLE = 3

# The Availability Lens compares the listings a shopper notices first (the top
# of the Google Shopping ranking) with the broader set of eligible listings.
# "First-seen" is defined as eligible listings whose original Google Shopping
# rank (the ``position`` field) falls on the first page, i.e. within the first
# ``FIRST_PAGE_SIZE`` results.  This is a deliberately modest, documented
# cutoff rather than a claim about what any particular screen showed.
FIRST_PAGE_SIZE = 10

# ---------------------------------------------------------------------------
# Core estimator implementation
# ---------------------------------------------------------------------------

def _load_cached_response(cache_dir: Path, query: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load a cached Google‑Shopping payload.

    When *query* is provided, only a cache whose stored query normalises to the
    same key is used (so unrelated products never leak in).  When *query* is
    ``None`` the newest ``google_shopping_*.json`` file is used – this preserves
    the historical default behaviour used by the CLI and tests.
    """
    if query:
        response = shopping.load_cached_for_query(cache_dir, query)
        if response is None:
            return None
        return {"response": response}

    candidates = list(Path(cache_dir).glob("google_shopping_*.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    with latest.open("r", encoding="utf-8") as f:
        return json.load(f)


def _product_key(item: Dict[str, Any]) -> str:
    """Identity of a product, so the same item is only ever counted once.

    Prefers SerpApi's ``product_id`` and falls back to the normalised title.
    """
    pid = item.get("product_id")
    if pid:
        return "pid:" + str(pid)
    return "title:" + shopping.normalize_title(item.get("title", ""))


# Human-readable reasons shown next to excluded listings, so every rejected
# item is explainable rather than silently dropped.
_MISMATCH_REASON = "different model, brand, or specification"
_AMBIGUOUS_REASON = "missing a requested specification or an unrequested variant"


def _exclusion_reason(classification: str, item: Dict[str, Any]) -> Optional[str]:
    """Return a short reason why *item* was excluded from the estimate."""
    if classification == "accessory":
        return shopping.accessory_reason(item.get("title", "")) or "not the product"
    if classification == "mismatch":
        return _MISMATCH_REASON
    if classification == "ambiguous":
        return _AMBIGUOUS_REASON
    return None


def _numeric_price(item: Dict[str, Any]) -> Optional[float]:
    """Return a numeric price from a listing or ``None`` if unavailable/invalid.

    ``extracted_price`` is the canonical numeric field.  When missing we fall
    back to parsing the ``price`` string for a leading number, but only if the
    conversion succeeds.
    """
    price = item.get("extracted_price")
    if isinstance(price, (int, float)):
        return float(price)
    # Fallback – try to extract a number from the raw price string.
    raw = item.get("price")
    if isinstance(raw, str):
        # Remove currency symbols and commas.
        cleaned = raw.replace("₹", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _quartiles(sorted_vals: List[float]) -> Tuple[float, float]:
    """Return the first (Q1) and third (Q3) quartiles.

    The implementation follows the *nearest‑rank* method used by the
    ``statistics.quantiles`` function with ``method='inclusive'`` – i.e. the
    25 % and 75 % positions are calculated as ``ceil(p * n)`` where *p* is the
    percentile and *n* the sample size.
    """
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("empty list for quartile calculation")
    # Position index is 1‑based; convert to 0‑based later.
    q1_pos = int((0.25 * n + 0.5))  # round to nearest integer
    q3_pos = int((0.75 * n + 0.5))
    # Clamp to valid index range.
    q1_idx = max(0, min(n - 1, q1_pos - 1))
    q3_idx = max(0, min(n - 1, q3_pos - 1))
    return sorted_vals[q1_idx], sorted_vals[q3_idx]


def _statistics(prices: List[float]) -> Dict[str, Any]:
    """Calculate transparent statistics for a list of numeric prices.

    Returns a dictionary with keys:
    - ``count``: number of eligible listings
    - ``minimum`` / ``maximum``
    - ``median``
    - ``q1`` / ``q3`` (first and third quartiles)
    - ``spread`` (max – min)
    - ``confidence``: ``"low"`` when count < 5, otherwise ``"high"``
    """
    # Always return a full set of statistic keys, even when no data is available.
    if not prices:
        return {}
    sorted_prices = sorted(prices)
    cnt = len(sorted_prices)
    min_price = sorted_prices[0]
    max_price = sorted_prices[-1]
    med = median(sorted_prices)
    q1, q3 = _quartiles(sorted_prices)
    spread = max_price - min_price
    confidence = "low" if cnt < 5 else "high"
    return {
        "count": cnt,
        "minimum": min_price,
        "maximum": max_price,
        "median": med,
        "q1": q1,
        "q3": q3,
        "spread": spread,
        "confidence": confidence,
    }


def _item_rank(item: Dict[str, Any], fallback: int) -> int:
    """Return the listing's original Google Shopping rank.

    Uses the provider's ``position`` field when it is a positive integer and
    otherwise falls back to *fallback* (the listing's 1-based position in the
    response) so ordering is always defined even when rank is missing.
    """
    pos = item.get("position")
    try:
        pos = int(pos)
    except (TypeError, ValueError):
        return fallback
    return pos if pos > 0 else fallback


def _group_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise one group of eligible listings for the Availability Lens.

    Only listings that carry a usable numeric price contribute to the
    statistics, so a missing price can never be invented.  ``sufficient`` is
    True only when there are at least :data:`MIN_ELIGIBLE` priced observations.
    """
    prices = [p for p in (_numeric_price(it) for it in items) if p is not None]
    ranks = [it["_rank"] for it in items if isinstance(it.get("_rank"), int)]
    return {
        "listing_count": len(items),
        "priced_count": len(prices),
        "prices": sorted(prices),
        "statistics": _statistics(prices),
        "sufficient": len(prices) >= MIN_ELIGIBLE,
        "rank_min": min(ranks) if ranks else None,
        "rank_max": max(ranks) if ranks else None,
    }


def _availability_lens(
    eligible_items: List[Dict[str, Any]],
    first_page_size: int = FIRST_PAGE_SIZE,
) -> Dict[str, Any]:
    """Build the first-seen vs broader-eligible comparison.

    The first-seen group is a *subset* of the broader group (every first-seen
    listing is also eligible), so the two groups are explicitly not independent
    samples.  The comparison is only described as comparable when both groups
    have enough priced observations.
    """
    first_items = [
        it for it in eligible_items
        if isinstance(it.get("_rank"), int) and it["_rank"] <= first_page_size
    ]
    first = _group_summary(first_items)
    broader = _group_summary(eligible_items)

    comparable = bool(first["sufficient"] and broader["sufficient"])
    difference = None
    if comparable:
        first_med = first["statistics"]["median"]
        broad_med = broader["statistics"]["median"]
        delta = first_med - broad_med
        percent = (delta / broad_med * 100.0) if broad_med else None
        if percent is None or abs(percent) < 1.0:
            direction = "similar"
        elif percent > 0:
            direction = "higher"
        else:
            direction = "lower"
        difference = {
            "median_delta": delta,
            "abs_median_delta": abs(delta),
            "percent": percent,
            "direction": direction,
        }

    return {
        "first_page_size": first_page_size,
        "first_seen": first,
        "broader": broader,
        "comparable": comparable,
        # First-seen is, by construction, wholly contained in the broader set.
        "overlap_count": len(first_items),
        "first_is_subset_of_broader": True,
        "difference": difference,
    }


def estimate_price(
    cache_dir: Path = DEFAULT_CACHE_DIR,
    query: Optional[str] = None,
    spec: Optional[Any] = None,
) -> Dict[str, Any]:
    """Main entry point – produce an evidence‑based price estimate.

    Loads the cached Google‑Shopping response for *query* (or the newest cache
    when *query* is ``None``), de‑duplicates items, classifies them against the
    product spec, and computes statistics on eligible observations only:
    confirmed listings, plus a single aggregated listing per product when that
    product has no independent listing.  Ambiguous, mismatch and accessory
    listings are retained in the output for reference but excluded from the
    calculation.  Aggregated entries are shown separately (so nothing is
    double‑counted) yet are still eligible when they are the only evidence.
    """
    if spec is None:
        spec = build_spec(query) if query else build_spec(shopping.DEFAULT_SPEC_QUERY)

    payload = _load_cached_response(cache_dir, query=query)
    if payload is None:
        return {
            "error": "no_cache",
            "reason": "No cached market data is available for this search.",
        }

    results = payload.get("response", {}).get("shopping_results", [])
    # Preserve the original Google Shopping ordering before de-duplicating:
    # each listing keeps its rank (``position``) so the Availability Lens can
    # distinguish the listings seen first from the broader eligible set.
    for index, item in enumerate(results):
        item["_rank"] = _item_rank(item, index + 1)
    # Deduplicate first – this mirrors the behaviour of the CLI utilities.
    unique_items, dup_count = deduplicate_items(results)

    confirmed: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    accessories: List[Dict[str, Any]] = []  # cases/covers/parts, not the product
    aggregated: List[Dict[str, Any]] = []  # listings with multiple_sources flag

    for item in unique_items:
        classification = classify_item(item, spec)
        # Record the outcome and a human-readable reason for every listing so
        # the results page can explain each accepted or excluded item.
        item["classification"] = classification
        item["exclusion"] = _exclusion_reason(classification, item)
        # Flag multi‑source listings for reporting; they are NOT promoted.
        item["multi_source_flag"] = bool(item.get("multiple_sources"))
        multi = bool(item.get("multiple_sources"))
        if multi:
            item["_original_classification"] = classification
        # A listing offered by several sellers is still judged on its own
        # merits.  Only a genuine product match belongs in the aggregated
        # "verified matches" group; mismatches and accessories keep their own
        # (excluded) sections so the aggregated group never overstates certainty.
        if classification == "confirmed":
            (aggregated if multi else confirmed).append(item)
        elif classification == "ambiguous":
            ambiguous.append(item)
        elif classification == "accessory":
            accessories.append(item)
        else:
            mismatches.append(item)

    # Build the list of eligible observations.  Independent confirmed listings
    # are always used.  An aggregated listing represents one product offered by
    # several sellers, so each product is counted at most once: aggregated
    # confirmed listings are used only when that product has no independent
    # listing, and never twice.  This keeps strong matches that appear *only* in
    # aggregated form eligible without over-counting the same item.
    confirmed_keys = {_product_key(it) for it in confirmed}
    aggregated_eligible: List[Dict[str, Any]] = []
    used_agg_keys = set()
    for it in aggregated:
        if it.get("_original_classification") != "confirmed":
            continue
        key = _product_key(it)
        if key in confirmed_keys or key in used_agg_keys:
            continue
        used_agg_keys.add(key)
        aggregated_eligible.append(it)

    eligible_items = confirmed + aggregated_eligible
    confirmed_prices = [
        p for p in (_numeric_price(it) for it in eligible_items) if p is not None
    ]

    stats = _statistics(confirmed_prices)

    # Availability Lens: compare the first-seen listings with the broader set.
    availability = _availability_lens(eligible_items)

    # Count listings excluded due to missing or invalid price.
    excluded_missing_price = len(
        [it for it in eligible_items if _numeric_price(it) is None]
    )

    # Summary of counts for reporting.
    summary = {
        "total_cached": len(results),
        "unique_items": len(unique_items),
        "confirmed": len(confirmed),
        "ambiguous": len(ambiguous),
        "mismatches": len(mismatches),
        "accessories": len(accessories),
        "aggregated": len(aggregated),
        "aggregated_used": len(aggregated_eligible),
        "excluded_missing_price": excluded_missing_price,
        "eligible_price_count": len(confirmed_prices),
    }

    # Ensure confidence is low for market-wide estimate.
    if "confidence" in stats:
        stats["confidence"] = "low"

    # Build evidence sections.
    evidence = {
        "confirmed": _summary_items(confirmed),
        "ambiguous": _summary_items(ambiguous),
        "mismatches": _summary_items(mismatches),
        "accessories": _summary_items(accessories),
        "aggregated": _summary_items(aggregated),
    }

    # Insufficient evidence handling.
    if summary["eligible_price_count"] < MIN_ELIGIBLE:
        return {
            "status": "insufficient_evidence",
            "reason": "Fewer than three eligible price observations; cannot produce a reliable market estimate.",
            "available_prices": confirmed_prices,
            "summary": summary,
            "evidence": evidence,
            "availability": availability,
        }

    # Sufficient data – return preliminary estimate.
    return {
        "status": "preliminary",
        "statistics": stats,
        "duplicate_count": dup_count,
        "summary": summary,
        "evidence": evidence,
        "availability": availability,
    }


def analyze_query(
    cache_dir: Path = DEFAULT_CACHE_DIR,
    query: str = "",
    allow_live: bool = True,
) -> Dict[str, Any]:
    """High‑level orchestration used by the web app.

    Order of operations:
      1. Look for a cache whose normalised query matches *query*.
      2. If none and *allow_live*, fetch from SerpApi (when a key is configured),
         save it, and use it.
      3. Otherwise return a structured error the UI can explain.

    Never falls back to cached data for a different product.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty_query", "query": query}

    spec = build_spec(query)

    cached = shopping.load_cached_for_query(cache_dir, query)
    origin = "cache"

    if cached is None:
        if not allow_live:
            return {"error": "no_cache", "query": query,
                    "reason": "No cached market data is available for this search."}
        if not shopping.has_api_key():
            return {"error": "missing_credentials", "query": query,
                    "reason": "Live lookup is unavailable because no SerpApi key is configured."}
        try:
            data = shopping.fetch_shopping(query)
        except shopping.SerpApiError as e:
            return {"error": "api_error", "query": query, "detail": str(e),
                    "reason": "The live market lookup failed."}
        except Exception as e:  # defensive: never crash the request
            return {"error": "api_error", "query": query, "detail": str(e),
                    "reason": "The live market lookup failed."}

        results = []
        if isinstance(data, dict):
            results = data.get("shopping_results") or []
        if not results:
            return {"error": "empty_response", "query": query,
                    "reason": "The provider returned no listings for this search."}

        # Only persist successful, non‑empty responses.
        shopping.save_response(cache_dir, query, "google_shopping", data)
        origin = "live"

    result = estimate_price(cache_dir=cache_dir, query=query, spec=spec)
    if "error" in result:
        return result
    result["origin"] = origin
    result["query"] = query
    return result

# ---------------------------------------------------------------------------
# Helper for command‑line usage (optional, not required by tests)
# ---------------------------------------------------------------------------

def _summary_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create a concise summary for a list of items.

    Each dict includes the title, numeric price (or ``None``), source, URL,
    condition (defaulting to ``"Unknown"``), the match classification, any
    exclusion reason, and a ``multiple_sources`` flag.
    This helper is used by :func:`estimate_price` to build the ``evidence``
    sections without duplicating logic.
    """
    summary = []
    for it in items:
        summary.append({
            "title": it.get("title"),
            "price": _numeric_price(it),
            "source": it.get("source"),
            "url": it.get("product_link"),
            "condition": it.get("second_hand_condition", "Unknown"),
            "classification": it.get("classification"),
            "exclusion": it.get("exclusion"),
            "rank": it.get("_rank"),
            "multiple_sources": bool(it.get("multiple_sources")),
        })
    return summary


if __name__ == "__main__":
    from pprint import pprint

    pprint(estimate_price())
