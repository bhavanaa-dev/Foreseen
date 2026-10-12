import os
import sys
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration & helper utilities
# ---------------------------------------------------------------------------

# The product that shipped with the original demo.  It is kept only as the
# default spec so that offline helpers and the legacy one-argument
# ``classify_item(item)`` call keep working exactly as before.
DEFAULT_SPEC_QUERY = "MacBook Air M1 8GB 256GB"


class SerpApiError(Exception):
    """Raised for any recoverable problem talking to SerpApi.

    The web application turns this into a friendly message instead of
    terminating the process.
    """


# Accepted environment-variable names for the SerpApi key, in priority order.
# ``SERPAPI_API_KEY`` is the canonical name; ``SERPAPI_KEY`` is accepted for
# backwards compatibility with older setups.
ENV_KEY_NAMES = ("SERPAPI_API_KEY", "SERPAPI_KEY")


def _env_path() -> Path:
    """Return the project-root .env path, based explicitly on this file.

    Using ``Path(__file__).resolve()`` avoids any dependence on the terminal's
    current working directory, so the app sees the key no matter where it is
    launched from.
    """
    return Path(__file__).resolve().parent.parent / ".env"


def load_env():
    """Load the project-root .env file reliably (path based on backend file)."""
    load_dotenv(dotenv_path=_env_path())


def get_api_key(required: bool = True):
    """Load .env from the project root and return the SerpApi key.

    Checks ``SERPAPI_API_KEY`` first, then ``SERPAPI_KEY`` (legacy).  When
    *required* is True a :class:`SerpApiError` is raised if no key is found;
    otherwise ``None`` is returned.  The key is read on the server only and is
    never returned to the browser or written to logs.
    """
    load_env()
    key = None
    for name in ENV_KEY_NAMES:
        value = os.getenv(name)
        if value:
            key = value
            break
    if not key:
        if required:
            raise SerpApiError(
                "SerpApi key is not configured on the server "
                "(set SERPAPI_API_KEY in the project .env)."
            )
        return None
    return key


def has_api_key() -> bool:
    """Return True when a SerpApi key is configured. Never raises."""
    try:
        return bool(get_api_key(required=False))
    except Exception:
        return False


def fetch_shopping(query: str, timeout: int = 10) -> dict:
    """Perform a Google Shopping search via SerpApi for *query*.

    Returns the parsed JSON response.  Raises :class:`SerpApiError` on missing
    credentials, network problems, timeouts, rate limits, HTTP errors, invalid
    JSON, or an ``error`` field in the payload.
    """
    api_key = get_api_key(required=True)
    params = {
        "engine": "google_shopping",
        "q": query,
        "gl": "in",
        "hl": "en",
        "api_key": api_key,
    }
    try:
        response = requests.get(
            "https://serpapi.com/search.json", params=params, timeout=timeout
        )
    except requests.exceptions.Timeout as e:
        # Deliberately do not interpolate the exception: request exceptions can
        # embed the full URL (including api_key) in their message.
        raise SerpApiError("SerpApi request timed out. Please try again.") from e
    except requests.exceptions.RequestException as e:
        raise SerpApiError("Network error while contacting SerpApi.") from e

    if response.status_code == 429:
        raise SerpApiError("SerpApi rate limit reached (HTTP 429). Try again later.")
    if response.status_code != 200:
        raise SerpApiError(f"SerpApi returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError as e:
        raise SerpApiError(f"SerpApi returned invalid JSON: {e}") from e

    if isinstance(data, dict) and data.get("error"):
        raise SerpApiError(f"SerpApi error: {data['error']}")
    return data


def save_response(cache_dir: Path, query: str, engine: str, data: dict) -> Path:
    """Save raw JSON response with metadata to cache directory."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_query = "_".join(query.split())  # simple sanitisation
    filename = f"{engine}_{safe_query}_{timestamp}.json"
    path = cache_dir / filename
    # Include extra metadata
    payload = {
        "query": query,
        "engine": engine,
        "timestamp": timestamp,
        "response": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def sanitize(text):
    """Return an ASCII‑safe string for console output.
    Non‑ASCII characters are removed.
    """
    if text is None:
        return "-"
    return str(text).encode("ascii", "ignore").decode("ascii")

# ---------------------------------------------------------------------------
# Query / product-spec parsing
#
# The matching pipeline below is deliberately product-agnostic.  It extracts
# whatever attributes a query actually contains (brand, model tokens,
# generations, storage/RAM/size capacities, condition) and never assumes that
# laptop-specific fields apply to every product.
# ---------------------------------------------------------------------------

# Common consumer brands.  A brand is treated as *soft*: it only matters when
# the listing explicitly states a conflicting brand.
BRANDS = {
    "apple", "samsung", "sony", "canon", "nikon", "fujifilm", "panasonic",
    "lg", "google", "motorola", "oneplus", "xiaomi", "redmi", "poco", "oppo",
    "vivo", "realme", "asus", "acer", "dell", "hp", "hewlett", "lenovo", "msi",
    "gigabyte", "asrock", "nvidia", "geforce", "amd", "radeon", "intel",
    "microsoft", "surface", "razer", "corsair", "logitech", "bose",
    "sennheiser", "jabra", "jbl", "beats", "akg", "technica", "gopro", "dji",
    "amazon", "echo", "kindle", "fitbit", "garmin", "huawei", "honor",
    "nothing", "valve", "nintendo", "xbox", "playstation", "toshiba", "philips",
    "hisense", "tcl", "nokia", "sandisk", "crucial", "kingston", "seagate",
    "western", "digital", "wd", "corsair",
}

# Words that describe condition rather than identity.  They are dropped from
# the cache key and never required for a match.
CONDITION_WORDS = {
    "used", "new", "refurbished", "refurb", "renewed", "remanufactured",
    "preowned", "pre", "owned", "unopened", "sealed", "open", "box",
    "secondhand", "second", "hand", "like", "excellent", "good", "fair",
    "grade", "working", "tested", "warranty",
}

# Generic specification nouns / filler that should not be treated as model
# identity (otherwise a listing that omits "ssd" would look like a mismatch).
STOPWORDS = {
    "with", "and", "the", "for", "a", "an", "of", "to", "in", "on", "by", "or",
    "from", "plus", "chip", "ram", "rom", "ssd", "hdd", "nvme", "emmc",
    "memory", "storage", "processor", "cpu", "gpu", "graphics", "card",
    "edition", "series", "model", "gen", "generation", "smartphone", "mobile",
    "cell", "cellphone", "wireless", "bluetooth", "wired", "original",
    "genuine", "brand",
}

# Variant suffixes (Pro/Max/Plus/...).  If a listing carries one of these that
# the query did not ask for, it is downgraded to "ambiguous" rather than being
# treated as an exact match (e.g. iPhone 13 vs iPhone 13 Pro Max).
VARIANT_SUFFIXES = {
    "pro", "max", "plus", "ultra", "mini", "lite", "se", "fe", "xl", "ti",
    "super", "xr", "gt", "gts",
}

# Cellular network technology.  Treated as an optional attribute (not identity):
# if the query names one (e.g. "Samsung A17 5G") then a listing that states a
# *conflicting* technology is a mismatch, and a listing that states none is only
# uncertain.  This never rejects a listing just because 5G is absent.
NETWORK_TOKENS = {"5g", "4g", "lte", "3g"}

_CAPACITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(gb|tb|mb)\b", re.I)
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:inch|inches|”|\")", re.I)
_BRAND_RE = None  # built lazily below


def _tokenize(text: str):
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _stem(token: str) -> str:
    """Very light singularisation so 'headphones' matches 'headphone'."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _capacities(text: str) -> set:
    """Extract storage/RAM/size capacities such as 256gb, 1tb, 13in."""
    t = (text or "").lower()
    caps = set()
    for m in _CAPACITY_RE.finditer(t):
        caps.add(f"{m.group(1)}{m.group(2)}")
    for m in _SIZE_RE.finditer(t):
        caps.add(f"{m.group(1)}in")
    return caps


def _networks(text: str) -> set:
    """Extract cellular network technologies (5g/4g/lte) with word boundaries."""
    t = (text or "").lower()
    return {tok for tok in NETWORK_TOKENS if re.search(r"\b" + tok + r"\b", t)}


def _generations(text: str):
    """Return (families, values) for chip/CPU generations found in *text*.

    Different *families* (Apple silicon vs Intel vs AMD ...) are a contradiction
    and therefore a mismatch.  A different generation within the same family
    (M1 vs M2) is only a missing spec, handled later as "ambiguous".
    """
    t = (text or "").lower()
    families, values = set(), set()

    # Apple silicon is M1..M4 only.  Bounding the digit stops generic model
    # numbers such as "M17" (Samsung Galaxy M17) or "A17" being read as chips.
    for m in re.finditer(r"\bm([1-4])(?:pro|max|ultra)?\b", t):
        families.add("apple_silicon")
        values.add("m" + m.group(1))
    for m in re.finditer(r"\bi([3579])\b", t):
        families.add("intel")
        values.add("i" + m.group(1))
    for m in re.finditer(r"\bi([3579])-?\d{3,}\b", t):
        families.add("intel")
        values.add("i" + m.group(1))
    if re.search(r"\b(intel|core|celeron|pentium|xeon)\b", t):
        families.add("intel")
        for kw in ("intel", "core", "celeron", "pentium", "xeon"):
            if re.search(r"\b" + kw + r"\b", t):
                values.add(kw)
    if re.search(r"\b(ryzen|threadripper)\b", t):
        families.add("amd")
        for kw in ("ryzen", "threadripper"):
            if re.search(r"\b" + kw + r"\b", t):
                values.add(kw)
    if re.search(r"\bsnapdragon\b", t):
        families.add("qualcomm")
        values.add("snapdragon")
    if re.search(r"\bdimensity\b", t):
        families.add("mediatek")
        values.add("dimensity")
    if re.search(r"\bexynos\b", t):
        families.add("samsung_soc")
        values.add("exynos")
    return families, values


_GEN_STRIP_PATTERNS = [
    re.compile(r"\bm[1-4](?:pro|max|ultra)?\b", re.I),
    re.compile(r"\bi[3579](?:-?\d{3,})?\b", re.I),
    re.compile(r"\b(intel|core|celeron|pentium|xeon|ryzen|threadripper|snapdragon|dimensity|exynos)\b", re.I),
]


def _strip_attributes(text: str) -> str:
    """Remove capacities / sizes / generations so model identity can be read.

    Identity must not include spec quantities (otherwise a listing with a
    *different* storage size would look like a different *product* instead of a
    merely uncertain one).
    """
    t = text or ""
    t = _CAPACITY_RE.sub(" ", t)
    t = _SIZE_RE.sub(" ", t)
    for pat in _GEN_STRIP_PATTERNS:
        t = pat.sub(" ", t)
    return t


@dataclass
class ProductSpec:
    """The salient attributes extracted from a user query."""

    raw: str
    identity_tokens: list = field(default_factory=list)
    identity_stem: set = field(default_factory=set)
    identity_compact: str = ""
    capacities: set = field(default_factory=set)
    networks: set = field(default_factory=set)
    gen_families: set = field(default_factory=set)
    gen_values: set = field(default_factory=set)
    brand: str = None  # type: ignore


def build_spec(query: str) -> ProductSpec:
    """Parse an arbitrary product query into a :class:`ProductSpec`.

    Works for any category: model numbers and words are kept as required
    identity, capacities/generations are extracted when present, and condition
    words are ignored.
    """
    raw = query or ""
    tokens = _tokenize(raw)
    brand = next((t for t in tokens if t in BRANDS), None)
    identity = [
        t for t in _tokenize(_strip_attributes(raw))
        if t not in CONDITION_WORDS and t not in STOPWORDS and t not in BRANDS
        and t not in NETWORK_TOKENS
    ]
    families, values = _generations(raw)
    return ProductSpec(
        raw=raw,
        identity_tokens=identity,
        identity_stem={_stem(t) for t in identity},
        identity_compact="".join(identity),
        capacities=_capacities(raw),
        networks=_networks(raw),
        gen_families=families,
        gen_values=values,
        brand=brand,
    )


def normalize_query_for_cache(query: str) -> str:
    """Normalise a query into a stable cache key.

    Condition words, filler and brand are removed so that variants such as
    "Apple MacBook Air M1 8GB 256GB" and "MacBook Air M1 8GB 256GB used" map to
    the same key.  Model numbers, generations and capacities are preserved.
    """
    tokens = _tokenize(query)
    kept = [
        t for t in tokens
        if t not in CONDITION_WORDS and t not in STOPWORDS and t not in BRANDS
    ]
    return " ".join(kept)


# ---------------------------------------------------------------------------
# Accessory / spare-part detection (product-agnostic)
#
# Accessories and spare parts often carry the *same* model words as the product
# itself ("case for Samsung Galaxy A17 5G", "A17 5G LCD screen"), so identity
# matching alone would happily count them.  We detect them with word-bounded
# accessory nouns instead, and keep them in a separate "accessory" bucket so
# they never enter the price statistics.  The lexicon is generic (it does not
# depend on any single brand or category).
# ---------------------------------------------------------------------------

_ACCESSORY_PATTERNS = [
    (
        "case or cover",
        re.compile(
            r"\b(cases?|covers?|bumpers?|shells?|sleeves?|pouches?|holsters?|"
            r"skins?|stickers?|decals?|wraps?|vinyl)\b",
            re.I,
        ),
    ),
    (
        "back panel or housing",
        re.compile(r"\b(back ?panel|back ?glass|back ?housing|housing|chassis)\b", re.I),
    ),
    (
        "screen protector",
        re.compile(
            r"\b(screen ?protector|screen ?guard|tempered glass|protector|guards?)\b",
            re.I,
        ),
    ),
    (
        "charger, cable or adapter",
        re.compile(
            r"\b(chargers?|adapters?|adaptors?|cables?|cords?|plugs?|brick)\b", re.I
        ),
    ),
    (
        "replacement or spare part",
        re.compile(
            r"\b(replacement (screen|display|battery|part|panel)|replacements?|"
            r"spare ?parts?|spares?)\b",
            re.I,
        ),
    ),
    (
        "internal or display part",
        re.compile(
            r"\b(lcd (screen|display|panel)|display assembly|screen assembly|"
            r"digitizer|motherboard|flex cable|charging port|batter(?:y|ies))\b",
            re.I,
        ),
    ),
    (
        "manual or guide, not the product",
        re.compile(
            r"\b(manuals?|user ?guide|guide|instruction|step.?by.?step|book)\b", re.I
        ),
    ),
    (
        "accessory (other language)",
        re.compile(
            r"\b(etui|h[uü]lle|huelle|funda|fundas|capa|coque|custodia|housse|"
            r"rahmen|carcasa|recambio)\b",
            re.I,
        ),
    ),
    (
        "compatible with another device",
        re.compile(
            r"\bcompatible\b|\bfor\s+(samsung|apple|iphone|ipad|macbook|galaxy|"
            r"xiaomi|redmi|poco|oneplus|oppo|vivo|realme|google|pixel|sony|huawei|"
            r"honor|nokia|motorola|asus|acer|dell|lenovo|nvidia|geforce|amd|radeon|"
            r"intel)\b",
            re.I,
        ),
    ),
]


def accessory_reason(text: str):
    """Return a short reason when *text* looks like an accessory/spare part.

    Returns ``None`` for ordinary product listings.  The reason is a human
    readable label (e.g. ``"case or cover"``) so exclusions can be explained.
    """
    t = (text or "").lower()
    for label, pattern in _ACCESSORY_PATTERNS:
        if pattern.search(t):
            return label
    return None


# ---------------------------------------------------------------------------
# Classification (product-aware)
# ---------------------------------------------------------------------------

def _identity_satisfied(spec: ProductSpec, facts: dict) -> bool:
    """Return True when the listing carries every requested model token.

    Tokens are matched against the listing's words; short tokens (e.g. the "wh"
    in "WH-1000XM4") and tokens containing digits may also match as a substring
    of the listing's compact form, which reconciles hyphenated/joined model
    numbers such as "WH1000XM4".
    """
    tokens = spec.identity_tokens
    if not tokens:
        return True
    stem_set = facts["stem"]
    compact = facts["compact"]
    for tok in tokens:
        if _stem(tok) in stem_set:
            continue
        has_digit = any(ch.isdigit() for ch in tok)
        if tok in compact and (has_digit or len(tok) <= 3):
            continue
        return False
    return True


def _title_facts(item: dict) -> dict:
    title = item.get("title", "") or ""
    tokens = _tokenize(title)
    families, values = _generations(title)
    return {
        "tokens": tokens,
        "stem": {_stem(t) for t in tokens},
        "compact": _compact(title),
        "caps": _capacities(title),
        "networks": _networks(title),
        "families": families,
        "values": values,
        "brand": next((t for t in tokens if t in BRANDS), None),
    }


def classify_item(item: dict, spec: ProductSpec = None) -> str:
    """Classify a shopping result against a product spec.

    Returns one of:
      - "confirmed"  every attribute named in the query is present and the
                     listing is the product itself
      - "ambiguous"  the model matches but one or more attributes are missing
                     (or a variant the query did not request is present)
      - "mismatch"   a different product (different brand, chip family, or
                     missing model identity)
      - "accessory"  a case, cover, protector, charger, spare part, manual or
                     other add-on rather than the product itself

    ``spec`` defaults to the legacy MacBook Air M1 8GB 256GB spec so existing
    one-argument callers keep their historical behaviour.
    """
    if spec is None:
        spec = build_spec(DEFAULT_SPEC_QUERY)
    title = (item.get("title", "") or "").strip()
    if not title:
        return "mismatch"
    f = _title_facts(item)

    # A listing that is itself an accessory/spare part is not the product.
    # If the *query* also asked for that accessory (e.g. "phone case"), the
    # corresponding reason is ignored so such searches still work.
    query_reason = accessory_reason(spec.raw)
    listing_reason = accessory_reason(title)
    if listing_reason and listing_reason != query_reason:
        return "accessory"

    # A conflicting brand is a different product.
    if spec.brand and f["brand"] and spec.brand != f["brand"]:
        return "mismatch"

    # A different chip/CPU *family* is a different product.
    if spec.gen_families and (f["families"] - spec.gen_families):
        return "mismatch"

    # All requested model-identity tokens must be present.
    if spec.identity_tokens:
        if not _identity_satisfied(spec, f):
            return "mismatch"
    elif not spec.capacities and not spec.gen_values and not spec.networks:
        # Nothing at all to verify against -> never call it an exact match.
        return "ambiguous"

    # A requested network technology (e.g. 5G) is enforced only when the listing
    # states one: a conflicting technology is a different product, while a
    # listing that is silent about it stays merely uncertain.
    if spec.networks and f["networks"]:
        if not (f["networks"] & spec.networks):
            return "mismatch"
    elif spec.networks and not f["networks"]:
        return "ambiguous"

    # A variant the query did not request (Pro / Max / Ti ...) is not exact.
    extra_variants = (set(f["tokens"]) & VARIANT_SUFFIXES) - set(spec.identity_tokens)
    if extra_variants:
        return "ambiguous"

    caps_ok = spec.capacities.issubset(f["caps"])
    gens_ok = spec.gen_values.issubset(f["values"]) if spec.gen_values else True
    if caps_ok and gens_ok:
        return "confirmed"
    return "ambiguous"


# ---------------------------------------------------------------------------
# Backwards-compatible helpers (kept for the original tests / CLI)
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """Lower‑case and strip non‑alphanumeric characters for simple matching."""
    if not title:
        return ""
    return "".join(ch.lower() for ch in title if ch.isalnum())


def deduplicate_items(items: list) -> tuple:
    """Remove exact duplicates.
    Duplicate key is a tuple of (normalized title, extracted_price, source, product_link).
    Returns (unique_items, duplicate_count).
    """
    seen = set()
    unique = []
    dup_cnt = 0
    for it in items:
        key = (
            normalize_title(it.get("title")),
            it.get("extracted_price"),
            it.get("source"),
            it.get("product_link"),
        )
        if key in seen:
            dup_cnt += 1
            continue
        seen.add(key)
        unique.append(it)
    return unique, dup_cnt

# ---------------------------------------------------------------------------
# Pretty‑printing utilities
# ---------------------------------------------------------------------------

def print_summary(data: dict, max_items: int = 5):
    """Print a concise, audit‑friendly summary of shopping results.
    Includes title, numeric price, currency, seller, URL, condition, rating,
    review count and any multi‑source flag. Also prints a simple classification.
    """
    results = data.get("shopping_results", [])
    total = len(results)
    print(f"Total results: {total}")
    # De‑duplicate before printing to avoid clutter
    unique, dup_cnt = deduplicate_items(results)
    if dup_cnt:
        print(f"Removed {dup_cnt} exact duplicate listing(s).")
    for i, item in enumerate(unique[:max_items]):
        title = sanitize(item.get("title", "-"))
        extracted_price = item.get("extracted_price")
        price_raw = item.get("price")
        if extracted_price is not None:
            price_display = f"₹{extracted_price:,}"
        else:
            price_display = sanitize(price_raw)
        source = sanitize(item.get("source", "-"))
        link = sanitize(item.get("product_link", "-"))
        condition = sanitize(item.get("second_hand_condition", "Unknown"))
        rating = item.get("rating")
        reviews = item.get("reviews")
        multi = item.get("multiple_sources")
        classification = classify_item(item)
        print(f"[{i+1}] Title: {title}\n"
              f"    Price: {price_display}\n"
              f"    Seller: {source}\n"
              f"    URL: {link}\n"
              f"    Condition: {condition}\n"
              f"    Rating: {rating if rating is not None else '-'} (Reviews: {reviews if reviews is not None else '-'})\n"
              f"    Multiple Sources: {multi if multi is not None else '-'}\n"
              f"    Classification: {classification}\n")

# ---------------------------------------------------------------------------
# Cache lookup helpers
# ---------------------------------------------------------------------------

def load_cached_response(cache_dir: Path, query: str, engine: str = "google_shopping") -> dict:
    """Load the most recent cached JSON file for a given query by file name.
    The cache directory may contain many files; the function picks the newest
    file that matches the pattern ``{engine}_{safe_query}_*.json``.
    Returns the inner ``response`` dict that originally came from SerpApi.
    """
    safe_query = "_".join(query.split())
    pattern = f"{engine}_{safe_query}_*.json"
    matching = list(cache_dir.glob(pattern))
    if not matching:
        raise FileNotFoundError(f"No cached file matching {pattern} in {cache_dir}")
    latest = max(matching, key=lambda p: p.stat().st_mtime)
    with open(latest, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("response", {})


def load_cached_for_query(cache_dir: Path, query: str, engine: str = "google_shopping"):
    """Return the newest cached *response* whose stored query matches *query*.

    Matching is done on :func:`normalize_query_for_cache` so that condition
    words and brand variants do not create false misses, while different
    products (which normalise differently) never collide.  Returns ``None``
    when no matching cache exists.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return None
    target = normalize_query_for_cache(query)
    if not target:
        return None
    candidates = []
    for path in cache_dir.glob(f"{engine}_*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            continue
        stored = payload.get("query")
        if stored is None:
            continue
        if normalize_query_for_cache(stored) == target:
            candidates.append((path, payload))
    if not candidates:
        return None
    _, payload = max(candidates, key=lambda pair: pair[0].stat().st_mtime)
    return payload.get("response", {})

# ---------------------------------------------------------------------------
# Entry‑point (kept unchanged – still performs a live request when run directly)
# ---------------------------------------------------------------------------

def main():
    query = "MacBook Air M1 8GB 256GB used"
    try:
        data = fetch_shopping(query)
    except SerpApiError as e:
        print(f"Error: {e}")
        sys.exit(1)
    # Save raw response
    cache_dir = Path(__file__).resolve().parent.parent / "cache"
    saved_path = save_response(cache_dir, query, "google_shopping", data)
    print(f"Raw JSON saved to: {saved_path}")
    # Print concise summary
    print_summary(data)

if __name__ == "__main__":
    main()
