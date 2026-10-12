import os
from pathlib import Path
from flask import Flask, request, render_template_string, abort

# Ensure the project root .env is loaded for any future API calls (optional)
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)

# Import the estimator + high-level orchestration
try:
    from .price_estimator import estimate_price, analyze_query, MIN_ELIGIBLE
except ImportError:
    from price_estimator import estimate_price, analyze_query, MIN_ELIGIBLE

app = Flask(__name__)


def format_inr(value):
    """Format a numeric value as Indian rupees using Indian digit grouping.

    Returns an em dash for missing or invalid values. This only formats values
    that already exist in the estimator result; it never invents a price.
    """
    if value is None:
        return "\u2014"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    negative = number < 0
    number = abs(number)
    whole = int(number)
    fraction = int(round((number - whole) * 100))
    if fraction == 100:
        whole += 1
        fraction = 0
    digits = str(whole)
    if len(digits) > 3:
        last_three = digits[-3:]
        rest = digits[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        digits = ",".join(groups) + "," + last_three
    if fraction:
        digits += ".%02d" % fraction
    return ("-" if negative else "") + "\u20b9" + digits


# Expose the Indian-rupee formatter as a Jinja filter: {{ price|inr }}
app.jinja_env.filters["inr"] = format_inr


def _build_evidence_sections(result):
    """Map the estimator's evidence categories to consumer-facing sections.

    Every category is kept strictly separate so that confirmed, ambiguous,
    mismatched, accessory, and multi-source listings are never conflated.
    """
    evidence = result.get("evidence") or {}
    definitions = [
        (
            "confirmed",
            "Exact matches",
            "Specification match",
            "match",
            "These listings state every attribute you searched for. They are the "
            "listings behind the estimate above.",
        ),
        (
            "ambiguous",
            "Uncertain listings",
            "Needs verification",
            "possible",
            "These look like the right model but do not confirm every specification, "
            "so we can't be certain they match. They are shown for context and are not "
            "used in the estimate.",
        ),
        (
            "mismatches",
            "Mismatches",
            "Different specification",
            "different",
            "These are related products with a different model, brand, or "
            "specification. They are not part of the estimate.",
        ),
        (
            "accessories",
            "Accessories & parts",
            "Not the product",
            "different",
            "These are cases, covers, screen protectors, chargers, manuals or spare "
            "parts. They mention the product but are not the product, so they are "
            "excluded from the estimate.",
        ),
        (
            "aggregated",
            "Verified matches across sources",
            "Multiple sellers",
            "aggregate",
            "These are product matches offered by more than one seller. Each product "
            "is counted once in the estimate and shown separately here so the same "
            "item is never counted twice.",
        ),
    ]
    sections = []
    for key, title, badge, badge_class, blurb in definitions:
        items = evidence.get(key) or []
        sections.append({
            "key": key,
            "title": title,
            "badge": badge,
            "badge_class": badge_class,
            "blurb": blurb,
            "items": items,
        })
    return sections


def _build_availability_view(availability, result=None):
    """Turn the estimator's Availability Lens data into a render-ready view.

    Every number comes straight from the estimator's eligible listings; this
    only positions real prices on one shared linear scale and writes
    plain-language, data-derived explanations.  Nothing here invents a price
    or recommends a purchase price.
    """
    if not availability:
        return None
    first = availability.get("first_seen") or {}
    broader = availability.get("broader") or {}
    prices = list(broader.get("prices") or [])
    stats = broader.get("statistics") or {}
    count = broader.get("priced_count", 0)

    lo = stats.get("minimum", 0.0) if stats else 0.0
    hi = stats.get("maximum", 0.0) if stats else 0.0
    median = stats.get("median") if stats else None

    min_pos = _linear_position(lo, hi, lo)
    max_pos = _linear_position(lo, hi, hi)
    median_pos = _linear_position(lo, hi, median) if median is not None else 50.0
    median_align = "center"
    if median is not None:
        if median_pos < 12:
            median_align = "left"
        elif median_pos > 88:
            median_align = "right"

    first_row = _group_view(first, "Seen first", "top %s results" % availability.get("first_page_size"))
    broader_row = _group_view(broader, "All eligible listings", "every eligible listing")

    limitations = (
        "Google Shopping is not the entire market \u2014 it is only the listings "
        "this search returned. First-page listings are part of the broader "
        "eligible set, so the two groups overlap and are not independent "
        "samples. This view describes the evidence that was found, not a "
        "recommended buying price."
    )

    return {
        "show": bool(count or first.get("listing_count") or broader.get("listing_count")),
        "first_page_size": availability.get("first_page_size"),
        "count": count,
        "listing_count": broader.get("listing_count", 0),
        "single": count == 1,
        "has_prices": bool(stats),
        "median": median,
        "median_label": ("only listing" if count == 1 else "median") if median is not None else "",
        "median_pos": round(median_pos, 2),
        "median_align": median_align,
        "minimum": lo,
        "maximum": hi,
        "min_pos": round(min_pos, 2),
        "max_pos": round(max_pos, 2),
        "q1": stats.get("q1") if stats else None,
        "q3": stats.get("q3") if stats else None,
        "has_quartiles": bool(stats) and count >= 4,
        "dots": _price_dots(prices, lo, hi),
        "compact": _outlier_zoom(prices, stats),
        "range_explanation": _range_explanation(stats, count),
        "insights": _lens_insights(stats, count, _outlier_zoom(prices, stats)),
        "first": first_row,
        "broader": broader_row,
        "difference_text": _difference_text(
            first_row, broader_row,
            availability.get("comparable", False), availability.get("difference"),
        ),
        "limitations": limitations,
        "confidence": "low",
        "links": _evidence_links(result),
    }


def _linear_position(lo, hi, value):
    """Map a real price to a 0-100% position on one shared linear scale.

    All markers use the same numeric scale; positions are strictly
    proportional to the actual prices.  A single shared scale is used so no
    marker can misrepresent or distort a price.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 50.0
    if lo is None or hi is None or hi <= lo or value != value:
        return 50.0
    return round(max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0)), 2)


def _price_dots(prices, lo, hi):
    """One marker per distinct eligible price, noting how many listings share it."""
    counts = {}
    for price in prices:
        try:
            key = round(float(price))
        except (TypeError, ValueError):
            continue
        counts[key] = counts.get(key, 0) + 1
    dots = []
    for value in sorted(counts):
        dots.append({
            "pos": _linear_position(lo, hi, value),
            "label": format_inr(value),
            "count": counts[value],
        })
    return dots


def _outlier_zoom(prices, stats):
    """Build an optional, clearly-labelled zoomed scale for extreme outliers.

    The full range is always shown on the main scale; this only offers a
    second linear scale over the central range so the bulk of prices stays
    readable.  Returns ``None`` when there is nothing to zoom (so the primary
    view stays a single, simple linear scale).
    """
    if not stats or len(prices) < 4:
        return None
    q1 = stats.get("q1")
    q3 = stats.get("q3")
    if q1 is None or q3 is None or q3 <= q1:
        return None
    iqr = q3 - q1
    lo = stats["minimum"]
    hi = stats["maximum"]
    zlo = max(lo, q1 - 1.5 * iqr)
    zhi = min(hi, q3 + 1.5 * iqr)
    outside = [p for p in prices if p < zlo or p > zhi]
    if not outside or (zhi - zlo) >= 0.9 * (hi - lo) or zhi <= zlo:
        return None
    return {
        "lo": zlo,
        "hi": zhi,
        "lo_label": format_inr(zlo),
        "hi_label": format_inr(zhi),
        "excluded": len(outside),
        "outside_max": format_inr(max(outside)),
        "dots": _price_dots([p for p in prices if zlo <= p <= zhi], zlo, zhi),
        "median_pos": _linear_position(zlo, zhi, stats["median"]),
    }


def _group_view(group, name, sub):
    """View model for one Availability Lens group (first page or broader set)."""
    stats = group.get("statistics") or {}
    priced = group.get("priced_count", 0)
    return {
        "name": name,
        "sub": sub,
        "listing_count": group.get("listing_count", 0),
        "priced_count": priced,
        "sufficient": group.get("sufficient", False),
        "has_stats": bool(stats),
        "single": priced == 1,
        "stats": stats,
        "median": stats.get("median") if stats else None,
    }


def _range_explanation(stats, count):
    """A concise, data-derived description of the observed price spread."""
    if not stats or count == 0:
        return "No eligible listing with a usable price was found."
    lo = stats["minimum"]
    hi = stats["maximum"]
    med = stats["median"]
    if count == 1:
        return "Only one eligible price was found, so there is no range to compare."
    ratio = (hi - lo) / med if med else 0.0
    if ratio <= 0.15:
        return "The observed prices are closely grouped around the middle value."
    if ratio >= 0.5 or (lo and hi / lo >= 2):
        return "The observed prices vary considerably across the listings we found."
    return "The observed prices vary moderately across the listings we found."


def _lens_insights(stats, count, compact):
    """Plain-language takeaways generated only from the observed evidence."""
    lines = []
    if count == 0:
        lines.append("No eligible listing carried a usable price, so there is nothing to chart yet.")
    elif count == 1:
        lines.append("We found a single eligible listing, so this is one observation rather than a market price.")
    else:
        lines.append(_range_explanation(stats, count))
        if count < MIN_ELIGIBLE:
            lines.append("We found only %d matching listing%s, so this estimate is preliminary." % (
                count, "" if count == 1 else "s"))
        elif count < 5:
            lines.append("This reading rests on %d listings \u2014 a small sample, so treat it as indicative." % count)
    if stats and count >= 4:
        lines.append("About half the listings sit between %s and %s." % (
            format_inr(stats["q1"]), format_inr(stats["q3"])))
    elif count >= 2:
        lines.append("There are too few listings to describe a middle half of the range.")
    if compact:
        lines.append("One price (%s) sits far from the rest; it stays on the full scale so the true range is not hidden." % compact["outside_max"])
    lines.append("These are the listings this one search returned from Google Shopping, not the whole market.")
    return lines


def _difference_text(first_row, broader_row, comparable, difference):
    """Compare the first-page group with the broader set in plain language."""
    first_n = first_row["priced_count"]
    if comparable and difference:
        direction = difference.get("direction")
        percent = difference.get("percent")
        if direction == "similar" or percent is None:
            lead = "Eligible prices on the first page are in line with the broader set (medians within 1%)."
        else:
            word = "higher" if direction == "higher" else "lower"
            lead = "Eligible prices on the first page are about %d%% %s than the broader set." % (
                round(abs(percent)), word)
        return lead + (
            " The first-page listings are part of the broader set, so this is a "
            "contrast within one search rather than a comparison of independent samples."
        )
    if first_n == 0:
        return "No eligible listing on the first page had a usable price, so there is no first-page price to compare."
    if first_n == 1:
        return "Only one eligible listing appeared in the first-page group, so we cannot establish a typical first-page price."
    if first_n == 2:
        return "The first page had only two eligible priced listings, so a first-page median is not reliable yet."
    return "The broader eligible set has too few priced listings for a reliable comparison yet."


def _evidence_links(result):
    """Links to the underlying confirmed/aggregated listings, when available."""
    if not result:
        return []
    evidence = result.get("evidence") or {}
    links = []
    for item in (evidence.get("confirmed") or []) + (evidence.get("aggregated") or []):
        url = item.get("url")
        if not url:
            continue
        links.append({
            "title": item.get("title") or "Listing",
            "price": item.get("price"),
            "url": url,
            "rank": item.get("rank"),
        })
    return links


# ---------------------------------------------------------------------------
# Shared presentation layer
#
# The original app rendered one inline template via render_template_string.
# We keep that architecture (no new dependencies, no second app) and split the
# markup into small, reusable string fragments so the homepage and the results
# page share the same ivory/forest-green editorial shell.
# ---------------------------------------------------------------------------

BASE_CSS = """
/* ============================== tokens ============================= */
* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; scroll-padding-top: calc(var(--nav-h) + 20px); }
:root {
  --ivory: #F7F6F0;
  --ivory-2: #FCFBF7;
  --paper: #FFFFFF;
  --green: #254D3A;
  --green-700: #1B3A2B;
  --green-600: #2F5C46;
  --sage: #DCE6D6;
  --stone: #E9E5DA;
  --charcoal: #20251F;
  --muted: #575E52;
  --dim: #8A9084;
  --pistachio: #B9CFAB;
  --line: rgba(32, 37, 31, .14);
  --line-soft: rgba(32, 37, 31, .08);
  --radius: 16px;
  --radius-lg: 26px;
  --radius-sm: 10px;
  --maxw: 1200px;
  --nav-h: 72px;
  --shadow-sm: 0 12px 28px -20px rgba(27, 58, 43, .5);
  --shadow: 0 42px 84px -48px rgba(27, 58, 43, .6);
  --serif: Georgia, "Iowan Old Style", "Times New Roman", serif;
  --sans: "Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif;
}
body {
  margin: 0;
  font-family: var(--sans);
  color: var(--charcoal);
  background: var(--ivory);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(900px 620px at 88% -12%, rgba(220, 230, 214, .8), transparent 60%),
    radial-gradient(720px 520px at -6% 22%, rgba(233, 229, 218, .75), transparent 58%);
}
a { color: inherit; text-decoration: none; }
svg { display: block; }
img { max-width: 100%; display: block; }
:focus-visible { outline: 2px solid var(--green); outline-offset: 3px; border-radius: 8px; }
.wrap { position: relative; z-index: 1; max-width: var(--maxw); margin: 0 auto; padding: 0 28px; }
[id] { scroll-margin-top: calc(var(--nav-h) + 20px); }
.visually-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}

/* ============================== header ============================= */
.site-nav {
  position: sticky; top: 0; z-index: 60;
  background: rgba(247, 246, 240, .84);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line-soft);
}
.nav-inner { max-width: var(--maxw); margin: 0 auto; padding: 16px 28px; display: flex; align-items: center; gap: 28px; }
.brand { display: flex; align-items: center; gap: 11px; }
.brand-mark { width: 36px; height: 36px; border-radius: 12px; display: grid; place-items: center; background: var(--green); box-shadow: var(--shadow-sm); }
.brand-name { font-weight: 700; letter-spacing: .28em; font-size: .92rem; color: var(--green); }
.nav-links { margin-left: auto; display: flex; gap: 26px; font-size: .92rem; color: var(--muted); }
.nav-links a { transition: color .15s ease; }
.nav-links a:hover { color: var(--green); }
.nav-search {
  display: inline-flex; align-items: center; gap: 9px; padding: 11px 18px; border-radius: 999px;
  background: var(--green); color: var(--ivory); font-weight: 600; font-size: .88rem;
  box-shadow: var(--shadow-sm); transition: transform .15s ease, background .15s ease;
}
.nav-search:hover { background: var(--green-700); transform: translateY(-1px); }
.nav-search svg { width: 16px; height: 16px; }

/* =============================== hero ============================== */
.hero { position: relative; z-index: 1; padding: 64px 0 44px; }
.hero-stage { position: relative; display: grid; grid-template-columns: 1.12fr .88fr; align-items: center; }
.hero-art {
  position: relative; border-radius: var(--radius-lg); overflow: hidden; min-height: 470px;
  border: 1px solid var(--line); background: linear-gradient(140deg, var(--sage), var(--stone));
  box-shadow: var(--shadow);
}
.hero-art img { width: 100%; height: 100%; object-fit: cover; }
.hero-art .art-tag {
  position: absolute; left: 22px; top: 22px; padding: 8px 15px; border-radius: 999px;
  background: rgba(247, 246, 240, .92); border: 1px solid var(--line);
  font-size: .7rem; letter-spacing: .18em; text-transform: uppercase; color: var(--green);
}
.hero-copy {
  position: relative; z-index: 2; margin-left: -78px;
  background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius-lg);
  box-shadow: var(--shadow); padding: 44px 42px;
}
.kicker { font-size: .72rem; letter-spacing: .22em; text-transform: uppercase; color: var(--green-600); margin: 0 0 16px; }
.display { font-family: var(--serif); font-weight: 400; font-size: clamp(2.3rem, 4.8vw, 3.9rem); line-height: 1.03; letter-spacing: -.02em; margin: 0 0 20px; color: var(--charcoal); }
.display em { font-style: italic; color: var(--green); }
.hero-sub { color: var(--muted); font-size: 1.06rem; max-width: 46ch; margin: 0 0 26px; }
.search { display: flex; gap: 10px; background: var(--paper); border: 1px solid var(--line); border-radius: 999px; padding: 8px; box-shadow: var(--shadow-sm); }
.search input { flex: 1; min-width: 0; border: 0; background: transparent; font: inherit; font-size: 1rem; padding: 12px 18px; color: var(--charcoal); border-radius: 999px; }
.search input::placeholder { color: var(--dim); }
.btn-primary {
  border: 0; cursor: pointer; font: inherit; font-weight: 700; font-size: .96rem; white-space: nowrap;
  padding: 13px 26px; border-radius: 999px; background: var(--green); color: var(--ivory);
  transition: background .15s ease, transform .15s ease;
}
.btn-primary:hover { background: var(--green-700); transform: translateY(-1px); }
.examples { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.examples-label { color: var(--dim); font-size: .84rem; margin-right: 2px; }
.chip {
  cursor: pointer; font: inherit; font-size: .82rem; color: var(--green-700);
  background: var(--sage); border: 1px solid transparent; padding: 8px 14px; border-radius: 999px;
  transition: background .15s ease, color .15s ease;
}
.chip:hover { background: var(--pistachio); }

/* floating micro panels */
.micro {
  position: absolute; z-index: 4; width: 232px; padding: 16px 18px; border-radius: var(--radius);
  background: var(--paper); border: 1px solid var(--line); box-shadow: var(--shadow);
}
.micro-k { display: flex; align-items: center; gap: 8px; font-size: .68rem; letter-spacing: .16em; text-transform: uppercase; color: var(--green-600); margin-bottom: 8px; }
.micro-k .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px rgba(37, 77, 58, .12); flex: none; }
.micro-v { font-weight: 700; color: var(--charcoal); font-size: .95rem; line-height: 1.3; }
.micro-s { color: var(--dim); font-size: .82rem; margin-top: 4px; }
.micro-spec { right: -18px; top: -22px; }
.micro-evidence { left: -18px; bottom: -22px; }

/* ============================= collage ============================= */
.collage { position: relative; z-index: 1; padding: 76px 0 48px; }
.collage-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  grid-template-rows: 1.12fr 0.88fr;
  gap: 24px;
  aspect-ratio: 2.5 / 1;
  align-items: stretch;
}
.tile {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line);
  background: var(--ivory-2);
  box-shadow: var(--shadow-sm);
}
.tile-media {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  background: linear-gradient(140deg, var(--sage), var(--stone));
}
.tile-media img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}
.tile-cap {
  padding: 16px 22px 18px;
  background: var(--ivory-2);
  border-top: 1px solid var(--line);
}
.tile-cap span {
  display: block;
  font-size: .72rem;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--green-600);
  margin-bottom: 5px;
}
.tile-cap strong {
  display: block;
  font-family: var(--serif);
  font-weight: 400;
  font-size: 1.05rem;
  line-height: 1.32;
  color: var(--charcoal);
}
.tile-a { grid-column: 1; grid-row: 1 / 3; }
.tile-b { grid-column: 2; grid-row: 1; }
.tile-c { grid-column: 3; grid-row: 1 / 3; }
.tile-quote {
  grid-column: 2; grid-row: 2;
  display: flex; flex-direction: column; justify-content: center;
  padding: 30px; background: var(--stone);
}
.tile-quote blockquote { font-family: var(--serif); font-size: 1.24rem; line-height: 1.38; margin: 0 0 12px; color: var(--charcoal); }
.tile-quote cite { font-style: normal; font-size: .72rem; letter-spacing: .16em; text-transform: uppercase; color: var(--green-600); }

/* ============================= contrast ============================ */
.contrast { position: relative; z-index: 1; padding: 70px 0; }
.contrast-inner {
  display: grid; grid-template-columns: 1.06fr .94fr; align-items: stretch; overflow: hidden;
  border-radius: var(--radius-lg); background: var(--green); box-shadow: var(--shadow);
}
.contrast-copy { padding: 58px 54px; color: var(--ivory); }
.contrast-copy .kicker { color: var(--pistachio); }
.contrast-copy h2 { font-family: var(--serif); font-weight: 400; font-size: clamp(2rem, 3.6vw, 3rem); line-height: 1.05; letter-spacing: -.02em; margin: 0 0 18px; }
.contrast-copy h2 em { font-style: italic; color: var(--pistachio); }
.contrast-copy p { color: rgba(247, 246, 240, .82); max-width: 46ch; margin: 0; }
.contrast-art { position: relative; min-height: 340px; }
.contrast-art img { width: 100%; height: 100%; object-fit: cover; }

/* ============================== how =============================== */
.how { position: relative; z-index: 1; padding: 78px 0 20px; }
.how-head { max-width: 640px; margin: 0 0 58px; }
.how-head h2 { font-family: var(--serif); font-weight: 400; font-size: clamp(1.9rem, 3.4vw, 2.7rem); letter-spacing: -.02em; margin: 0 0 12px; }
.how-head p { color: var(--muted); margin: 0; }
.how-step { display: grid; grid-template-columns: 7fr 5fr; gap: 52px; align-items: center; margin-bottom: 74px; }
.how-step.reverse { grid-template-columns: 5fr 7fr; }
.how-step.reverse .how-media { order: 2; }
.how-body h3 { font-family: var(--serif); font-weight: 400; font-size: 1.65rem; margin: 0 0 12px; color: var(--charcoal); }
.how-body p { color: var(--muted); margin: 0; max-width: 44ch; }
.how-num { font-family: var(--serif); font-size: 1.3rem; color: var(--green-600); margin: 0 0 10px; letter-spacing: .06em; }
.how-media { position: relative; border-radius: var(--radius-lg); overflow: hidden; min-height: 300px; border: 1px solid var(--line); background: var(--sage); box-shadow: var(--shadow-sm); }
.how-media img { width: 100%; height: 100%; object-fit: cover; }

/* ============================== cta =============================== */
.cta { position: relative; z-index: 1; padding: 30px 0 100px; }
.cta-inner { text-align: center; padding: 24px; }
.cta-inner h2 { font-family: var(--serif); font-weight: 400; font-size: clamp(1.8rem, 3vw, 2.4rem); letter-spacing: -.02em; margin: 0 0 12px; }
.cta-inner p { color: var(--muted); margin: 0 0 24px; }

/* ============================= results ============================ */
.results { position: relative; z-index: 1; }
.results-hero { padding: 46px 0 22px; }
.back-link { display: inline-flex; align-items: center; gap: 7px; margin-bottom: 22px; color: var(--green-600); font-weight: 600; font-size: .9rem; }
.back-link:hover { text-decoration: underline; }
.identity { display: flex; gap: 24px; align-items: center; flex-wrap: wrap; }
.identity-art { width: 100px; height: 100px; border-radius: var(--radius); overflow: hidden; border: 1px solid var(--line); background: var(--sage); flex: none; box-shadow: var(--shadow-sm); }
.identity-art img { width: 100%; height: 100%; object-fit: cover; }
.identity-copy h1 { font-family: var(--serif); font-weight: 400; font-size: clamp(1.8rem, 3.6vw, 2.7rem); letter-spacing: -.02em; margin: 0 0 8px; }
.identity-copy p { color: var(--muted); margin: 0; max-width: 60ch; }
.identity-copy .kicker { margin-bottom: 8px; }
.origin { display: inline-flex; align-items: center; gap: 8px; margin-top: 12px; padding: 6px 14px; border-radius: 999px; font-size: .78rem; font-weight: 600; letter-spacing: .02em; border: 1px solid var(--line); background: var(--ivory-2); color: var(--green-600); }
.origin .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; flex: none; }
.origin.live { color: var(--green); background: var(--sage); border-color: transparent; }
.origin.cached { color: var(--dim); }
.status { display: inline-flex; align-items: center; gap: 9px; font-weight: 700; font-size: .86rem; margin-top: 16px; padding: 8px 16px; border-radius: 999px; border: 1px solid var(--line); }
.status.preliminary { color: var(--green); background: var(--sage); border-color: transparent; }
.status.insufficient { color: #8a3b2f; background: #F0E4DE; border-color: transparent; }
.results-body { padding: 22px 0 90px; }

/* asymmetric insight grid */
.insight-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; margin: 6px 0 24px; }
.insight { padding: 26px 24px; border-radius: var(--radius); background: var(--ivory-2); border: 1px solid var(--line); box-shadow: var(--shadow-sm); }
.insight .label { font-size: .71rem; letter-spacing: .15em; text-transform: uppercase; color: var(--green-600); }
.insight .value { font-family: var(--serif); font-size: 1.95rem; color: var(--charcoal); margin-top: 10px; line-height: 1.1; }
.insight .sub { margin-top: 8px; color: var(--dim); font-size: .83rem; }
.insight.primary { background: var(--green); border-color: transparent; color: var(--ivory); }
.insight.primary .label { color: var(--pistachio); }
.insight.primary .value { color: var(--ivory); font-size: 2.5rem; }
.insight.primary .sub { color: rgba(247, 246, 240, .72); }
.span-5 { grid-column: span 5; }
.span-4 { grid-column: span 4; }
.span-3 { grid-column: span 3; }

/* badges */
.badge { display: inline-flex; align-items: center; font-size: .72rem; font-weight: 700; padding: 5px 12px; border-radius: 999px; letter-spacing: .02em; }
.badge.match { color: #1B3A2B; background: var(--pistachio); }
.badge.possible { color: #6b5a1f; background: #EFE7C8; }
.badge.different { color: #7a2f26; background: #F0DCD6; }
.badge.aggregate { color: #2f4560; background: #DCE4EC; }
.badge.low { color: #6b5a1f; background: #EFE7C8; }
.badge.high { color: #1B3A2B; background: var(--pistachio); }

/* panels */
.panel { background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius); padding: 30px; margin-bottom: 22px; box-shadow: var(--shadow-sm); }
.panel h3 { font-family: var(--serif); font-weight: 400; font-size: 1.3rem; margin: 0 0 12px; }
.panel p { color: var(--muted); margin: 0 0 12px; }
.panel p:last-child { margin-bottom: 0; }
.explain strong { color: var(--charcoal); }
.price-chips { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
.price-chip { font-weight: 700; color: var(--green); background: var(--sage); padding: 7px 15px; border-radius: 999px; font-size: .95rem; }

/* evidence + listings */
.evidence-wrap { margin-top: 44px; }
.evidence-intro { max-width: 720px; margin-bottom: 32px; }
.evidence-intro h2 { font-family: var(--serif); font-weight: 400; font-size: clamp(1.5rem, 2.6vw, 2rem); letter-spacing: -.02em; margin: 0 0 10px; }
.evidence-intro p { color: var(--muted); margin: 0; }
.evidence-section { margin-bottom: 38px; }
.evidence-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.evidence-head h3 { font-family: var(--serif); font-weight: 400; font-size: 1.3rem; margin: 0; }
.evidence-head .count { color: var(--dim); font-size: .86rem; }
.evidence-blurb { color: var(--muted); font-size: .92rem; margin: 0 0 18px; max-width: 780px; }
.listing-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.listing { display: flex; flex-direction: column; gap: 12px; padding: 22px; border-radius: var(--radius); background: var(--paper); border: 1px solid var(--line); box-shadow: var(--shadow-sm); transition: transform .16s ease, box-shadow .16s ease; }
.listing:hover { transform: translateY(-3px); box-shadow: var(--shadow); }
.listing .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.listing .title { font-weight: 600; font-size: .98rem; line-height: 1.4; margin: 0; }
.listing .price { font-family: var(--serif); font-size: 1.3rem; color: var(--green); white-space: nowrap; }
.listing .meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--dim); font-size: .84rem; }
.listing .meta .k { color: var(--dim); }
.listing .exclusion { margin: 0; color: var(--dim); font-size: .82rem; line-height: 1.45; }
.listing .exclusion .k { font-weight: 600; color: var(--dim); }
.listing .link { margin-top: auto; color: var(--green-600); font-weight: 600; font-size: .88rem; }
.listing .link:hover { text-decoration: underline; }
.listing .link.no-link { color: var(--dim); font-weight: 500; }

/* availability lens */
.lens { margin-top: 48px; }
.lens-head { max-width: 760px; margin-bottom: 22px; }
.lens-head h2 { font-family: var(--serif); font-weight: 400; font-size: clamp(1.5rem, 2.6vw, 2rem); letter-spacing: -.02em; margin: 0 0 8px; }
.lens-head p { color: var(--muted); margin: 0; }

.lens-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.lens-card2 { background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow-sm); padding: 22px 24px; }
.lens-card2.first { border-color: rgba(37,77,58,.35); background: linear-gradient(180deg, var(--sage), var(--ivory-2) 72%); }
.lens-card2 .k { font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; color: var(--green-600); font-weight: 700; }
.lens-card2 .big { font-family: var(--serif); font-size: 2.05rem; line-height: 1.05; color: var(--charcoal); margin-top: 10px; }
.lens-card2.first .big { color: var(--green-700); }
.lens-card2 .big .unit { font-family: var(--sans); font-size: .8rem; font-weight: 600; color: var(--muted); margin-left: 8px; }
.lens-card2 .meta { color: var(--muted); font-size: .86rem; margin-top: 8px; }

.lens-range { background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow-sm); padding: 16px 22px; margin-bottom: 16px; color: var(--muted); font-size: .94rem; }
.lens-range b { color: var(--charcoal); }

.scale-card { background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow-sm); padding: 26px 26px 20px; }
.scale-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px 18px; flex-wrap: wrap; margin-bottom: 28px; }
.scale-title { font-weight: 700; font-size: .92rem; color: var(--charcoal); }
.scale-sub { color: var(--muted); font-size: .82rem; }
.scale-track { position: relative; height: 42px; margin: 0 8px; }
.scale-line { position: absolute; left: 0; right: 0; top: 50%; height: 3px; transform: translateY(-50%); background: linear-gradient(90deg, var(--sage), var(--pistachio)); border-radius: 3px; }
.scale-dot { position: absolute; top: 50%; width: 10px; height: 10px; transform: translate(-50%, -50%); border-radius: 50%; background: var(--ivory-2); border: 2px solid var(--green-600); }
.scale-cap { position: absolute; top: 50%; width: 2px; height: 26px; transform: translate(-50%, -50%); background: var(--green-600); border-radius: 1px; }
.scale-median { position: absolute; top: 50%; width: 4px; height: 36px; transform: translate(-50%, -50%); background: var(--green-700); border-radius: 2px; }
.scale-tag { position: absolute; bottom: 30px; font-size: .76rem; font-weight: 700; color: var(--green-700); white-space: nowrap; }
.scale-tag.center { transform: translateX(-50%); }
.scale-tag.left { transform: translateX(0); }
.scale-tag.right { transform: translateX(-100%); }
.scale-axis { position: relative; height: 18px; margin: 10px 8px 0; }
.scale-axis .tick { position: absolute; top: 0; font-size: .78rem; color: var(--muted); }
.scale-axis .tick.left { left: 0; }
.scale-axis .tick.right { right: 0; }
.scale-axis .tick.center { left: 50%; transform: translateX(-50%); }
.scale-none { color: var(--dim); font-size: .85rem; margin: 0; padding: 6px 0; }

.lens-zoom { margin-top: 14px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--ivory-2); padding: 14px 18px 16px; }
.lens-zoom summary { cursor: pointer; font-weight: 700; font-size: .86rem; color: var(--green-600); }
.lens-zoom[open] summary { margin-bottom: 18px; }
.lens-zoom .scale-track { height: 36px; }
.zoom-note { color: var(--muted); font-size: .82rem; margin: 12px 0 0; }

.lens-meaning { margin-top: 16px; background: var(--sage); border-radius: var(--radius); padding: 22px 24px; }
.lens-meaning h3 { font-family: var(--serif); font-weight: 400; font-size: 1.2rem; margin: 0 0 12px; color: var(--green-700); }
.lens-meaning ul { margin: 0; padding-left: 20px; }
.lens-meaning li { color: var(--green-700); font-size: .94rem; line-height: 1.5; margin-bottom: 6px; }

.lens-compare { margin-top: 16px; background: var(--ivory-2); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow-sm); padding: 24px 26px; }
.lens-compare h3 { font-family: var(--serif); font-weight: 400; font-size: 1.2rem; margin: 0 0 6px; }
.compare-note { color: var(--muted); font-size: .84rem; margin: 0 0 16px; }
.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.compare-item { border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 16px 18px; background: var(--paper); }
.compare-item.first { border-color: rgba(37,77,58,.3); background: var(--sage); }
.compare-item .k { font-size: .72rem; letter-spacing: .12em; text-transform: uppercase; color: var(--green-600); font-weight: 700; }
.compare-item .v { font-family: var(--serif); font-size: 1.4rem; color: var(--charcoal); margin-top: 8px; }
.compare-item .v .u { font-family: var(--sans); font-size: .72rem; font-weight: 600; color: var(--muted); margin-left: 6px; letter-spacing: 0; text-transform: none; }
.compare-item .m { color: var(--muted); font-size: .82rem; margin-top: 6px; }
.compare-result { margin: 16px 0 0; color: var(--charcoal); font-size: .94rem; line-height: 1.5; }

.lens-details { margin-top: 16px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--ivory-2); padding: 18px 22px; }
.lens-details summary { cursor: pointer; font-weight: 700; font-size: .9rem; color: var(--green-600); }
.lens-details[open] summary { margin-bottom: 18px; }
.details-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px 20px; margin: 0 0 16px; }
.details-stats dt { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; }
.details-stats dd { margin: 2px 0 0; color: var(--charcoal); font-weight: 600; font-size: .95rem; }
.details-limits { color: var(--muted); font-size: .82rem; line-height: 1.5; margin: 0 0 14px; }
.details-links h4 { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 0 0 8px; }
.details-links ul { margin: 0; padding-left: 18px; }
.details-links li { font-size: .86rem; line-height: 1.5; margin-bottom: 6px; color: var(--charcoal); }
.details-links a { color: var(--green-600); }
.details-links .rank { color: var(--muted); }

/* empty state */
.empty { text-align: center; padding: 70px 26px; border-radius: var(--radius-lg); border: 1px dashed var(--line); background: var(--ivory-2); }
.empty .icon { width: 64px; height: 64px; margin: 0 auto 20px; border-radius: 50%; display: grid; place-items: center; background: var(--sage); color: var(--green); }
.empty h2 { font-family: var(--serif); font-weight: 400; font-size: 1.6rem; margin: 0 0 12px; }
.empty p { color: var(--muted); max-width: 560px; margin: 0 auto 24px; }
.empty .empty-hint { color: var(--dim); font-size: .9rem; }
a.btn-primary { display: inline-block; text-align: center; }
a.btn-primary:hover { text-decoration: none; }
.results a { color: var(--green-600); }
.results a:hover { text-decoration: underline; }
.link-back { color: var(--green-600); font-weight: 600; font-size: .9rem; }

/* ============================== footer ============================ */
.site-footer { position: relative; z-index: 1; margin-top: 30px; background: var(--green); color: rgba(247, 246, 240, .85); padding: 56px 0 30px; }
.footer-inner { max-width: var(--maxw); margin: 0 auto; padding: 0 28px; display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 40px; }
.footer-brand { display: flex; align-items: center; gap: 11px; }
.footer-brand .brand-mark { background: rgba(247, 246, 240, .14); box-shadow: none; }
.footer-brand .brand-name { color: var(--ivory); }
.footer-tag { color: rgba(247, 246, 240, .7); font-size: .95rem; margin: 16px 0 0; max-width: 36ch; }
.footer-col h4 { font-size: .72rem; letter-spacing: .18em; text-transform: uppercase; color: var(--pistachio); margin: 0 0 14px; }
.footer-col a { display: block; color: rgba(247, 246, 240, .82); font-size: .92rem; margin-bottom: 10px; }
.footer-col a:hover { color: var(--ivory); }
.footer-col p { color: rgba(247, 246, 240, .68); font-size: .92rem; margin: 0; max-width: 34ch; }
.footer-bottom { max-width: var(--maxw); margin: 42px auto 0; padding: 20px 28px 0; border-top: 1px solid rgba(247, 246, 240, .16); display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; color: rgba(247, 246, 240, .6); font-size: .82rem; }

/* ============================ responsive ========================== */
@media (max-width: 980px) {
  .hero-stage { grid-template-columns: 1fr; }
  .hero-art { min-height: 380px; }
  .hero-copy { margin-left: 0; margin-top: -40px; }
  .micro { position: relative; width: auto; left: auto; right: auto; top: auto; bottom: auto; margin-top: 14px; }
  .collage-grid { grid-template-columns: 1fr; grid-template-rows: auto; aspect-ratio: auto; }
  .tile, .tile-quote { grid-column: 1; grid-row: auto; }
  .tile-media { flex: none; aspect-ratio: 16 / 9; }
  .contrast-inner { grid-template-columns: 1fr; }
  .contrast-art { min-height: 260px; }
  .how-step, .how-step.reverse { grid-template-columns: 1fr; gap: 28px; }
  .how-step.reverse .how-media { order: 0; }
  .insight-grid { grid-template-columns: 1fr 1fr; }
  .insight, .insight.primary, .span-5, .span-4, .span-3 { grid-column: span 1; }
  .footer-inner { grid-template-columns: 1fr; gap: 30px; }
}
@media (max-width: 620px) {
  .wrap, .nav-inner { padding-left: 18px; padding-right: 18px; }
  .nav-links { display: none; }
  .nav-search span { display: none; }
  .nav-search { padding: 11px; }
  .search { flex-direction: column; border-radius: var(--radius); }
  .search input { width: 100%; }
  .btn-primary { width: 100%; }
  .collage-grid { grid-template-columns: 1fr; }
  .tile, .tile-quote { grid-column: 1; }
  .insight-grid { grid-template-columns: 1fr; }
  .identity-art { width: 84px; height: 84px; }
  .lens-cards { grid-template-columns: 1fr; }
  .compare-grid { grid-template-columns: 1fr; }
  .scale-card { padding: 20px 16px 16px; }
  .scale-head { margin-bottom: 22px; }
  .scale-track { margin: 0 4px; }
  .scale-axis { margin: 10px 4px 0; }
  .lens-compare, .lens-meaning { padding: 20px 18px; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  * { transition: none !important; }
  .listing:hover, .nav-search:hover, .btn-primary:hover { transform: none; }
}
"""

PAGE_HEAD = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '  <meta charset="utf-8">\n'
    '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "  <title>FORESEEN \u2014 See beyond the price</title>\n"
    '  <meta name="description" content="FORESEEN turns scattered used-market listings '
    'into clear, evidence-backed price insight so you can buy smarter.">\n'
    '  <meta name="theme-color" content="#F7F6F0">\n'
    '  <link rel="icon" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='9' fill='%23254D3A'/%3E"
    "%3Cpath d='M16 7c4 1.6 6.5 5 6.5 9.2 0 3.4-2.5 5.8-6.5 5.8s-6.5-2.4-6.5-5.8C9.5 12 12 8.6 16 7z' fill='%23F7F6F0'/%3E"
    "%3Cpath d='M16 11v9M16 14.5c1.6 0 3 .8 3.8 2.2M16 16.5c-1.6 0-3 .8-3.8 2.2' stroke='%23254D3A' stroke-width='1.4' fill='none' stroke-linecap='round'/%3E"
    '%3C/svg%3E">\n'
    "  <style>\n" + BASE_CSS + "\n  </style>\n"
    "</head>\n"
    "<body>\n"
)

BRAND_MARK_SVG = (
    '<svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true">'
    '<path d="M16 6c4.4 1.8 7 5.6 7 10.1 0 3.8-2.8 6.4-7 6.4s-7-2.6-7-6.4C9 11.6 11.6 7.8 16 6z" fill="#F7F6F0"/>'
    '<path d="M16 11v10M16 15c1.8 0 3.3.9 4.2 2.4M16 17.4c-1.8 0-3.3.9-4.2 2.4" stroke="#254D3A" stroke-width="1.6" stroke-linecap="round"/>'
    "</svg>"
)

SEARCH_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/></svg>'
)

NAV = (
    '<header class="site-nav">\n'
    '  <div class="nav-inner">\n'
    '    <a class="brand" href="/" aria-label="FORESEEN home">\n'
    '      <span class="brand-mark">' + BRAND_MARK_SVG + "</span>\n"
    '      <span class="brand-name">FORESEEN</span>\n'
    "    </a>\n"
    '    <nav class="nav-links" aria-label="Primary">\n'
    '      <a href="/#how">How it works</a>\n'
    '      <a href="/#evidence">Evidence</a>\n'
    '      <a href="/#search">Search</a>\n'
    "    </nav>\n"
    '    <a class="nav-search" href="/#search">' + SEARCH_ICON + "<span>Search products</span></a>\n"
    "  </div>\n"
    "</header>\n"
)

FOOTER = (
    '<footer class="site-footer">\n'
    '  <div class="footer-inner">\n'
    '    <div class="footer-brand-col">\n'
    '      <div class="footer-brand">\n'
    '        <span class="brand-mark">' + BRAND_MARK_SVG + "</span>\n"
    '        <span class="brand-name">FORESEEN</span>\n'
    "      </div>\n"
    '      <p class="footer-tag">See beyond the price. Evidence-based buying intelligence for the used market.</p>\n'
    "    </div>\n"
    '    <div class="footer-col">\n'
    "      <h4>Explore</h4>\n"
    '      <a href="/#how">How it works</a>\n'
    '      <a href="/#evidence">Evidence</a>\n'
    '      <a href="/#search">Search products</a>\n'
    "    </div>\n"
    '    <div class="footer-col">\n'
    "      <h4>Please note</h4>\n"
    "      <p>Prices are estimates drawn from cached market listings, not guarantees.</p>\n"
    "    </div>\n"
    "  </div>\n"
    '  <div class="footer-bottom">\n'
    "    <span>&copy; 2026 FORESEEN.</span>\n"
    "    <span>Estimates are directional, not appraisals.</span>\n"
    "  </div>\n"
    "</footer>\n"
)

SCRIPTS = (
    "<script>\n"
    "(function () {\n"
    "  var input = document.getElementById('query');\n"
    "  var chips = document.querySelectorAll('[data-example]');\n"
    "  for (var i = 0; i < chips.length; i++) {\n"
    "    chips[i].addEventListener('click', function () {\n"
    "      if (!input) return;\n"
    "      input.value = this.getAttribute('data-example') || '';\n"
    "      input.focus();\n"
    "      try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) {}\n"
    "    });\n"
    "  }\n"
    "  var form = input ? input.form : null;\n"
    "  if (form) {\n"
    "    form.addEventListener('submit', function () {\n"
    "      var btn = form.querySelector('button[type=\"submit\"], button:not([type])');\n"
    "      if (btn) { btn.disabled = true; btn.textContent = 'Analyzing\u2026'; }\n"
    "    });\n"
    "  }\n"
    "})();\n"
    "</script>\n"
)

HOME_BODY = """
<main>
  <section class="hero" id="search">
    <div class="wrap">
      <div class="hero-stage">
        <div class="hero-art">
          <img src="/static/images/hero-laptop.svg" alt="Illustration of a laptop showing a price trend chart">
          <span class="art-tag">Used-market intelligence</span>
        </div>
        <div class="hero-copy">
          <p class="kicker">Evidence, not guesswork</p>
          <h1 class="display">Buy smarter.<br><em>See the full picture.</em></h1>
          <p class="hero-sub">Prices alone don&rsquo;t tell the whole story. FORESEEN matches the exact specification, weighs real market listings, and shows how confident the answer really is.</p>
          <form class="search" method="post" action="/analyze" role="search">
            <label class="visually-hidden" for="query">Product search</label>
            <input type="text" id="query" name="query" value="{{ query|e }}" placeholder="Search any product, e.g. iPhone 13 128GB" required autocomplete="off" aria-describedby="search-hint">
            <button type="submit" class="btn-primary">Analyze</button>
          </form>
          <p id="search-hint" class="visually-hidden">Enter the product and any specification you care about, then press Analyze to see an evidence-backed estimate.</p>
          <div class="examples">
            <span class="examples-label">Try a category:</span>
            <button type="button" class="chip" data-example="MacBook Air M1 8GB 256GB">Laptop &middot; MacBook Air M1</button>
            <button type="button" class="chip" data-example="iPhone 13 128GB">Phone &middot; iPhone 13</button>
            <button type="button" class="chip" data-example="RTX 3080">GPU &middot; RTX 3080</button>
            <button type="button" class="chip" data-example="Apple Watch Series 9">Smartwatch &middot; Apple Watch Series 9</button>
            <button type="button" class="chip" data-example="WH-1000XM4">Headphones &middot; WH-1000XM4</button>
            <button type="button" class="chip" data-example="PS5">Gaming console &middot; PS5</button>
            <button type="button" class="chip" data-example="iPad Air">Tablet &middot; iPad Air</button>
          </div>
        </div>
        <aside class="micro micro-spec">
          <div class="micro-k"><span class="dot"></span>Specification match</div>
          <div class="micro-v">Chip, memory &amp; storage</div>
          <div class="micro-s">Only exact-spec listings inform the estimate</div>
        </aside>
        <aside class="micro micro-evidence">
          <div class="micro-k"><span class="dot"></span>Evidence quality</div>
          <div class="micro-v">Every figure is traceable</div>
          <div class="micro-s">Each number maps back to a real listing</div>
        </aside>
      </div>
    </div>
  </section>

  <section class="collage" id="evidence">
    <div class="wrap">
      <div class="collage-grid">
        <figure class="tile tile-a">
          <div class="tile-media"><img src="/static/images/hero-laptop.svg" alt="Illustration of a laptop showing a price trend chart"></div>
          <figcaption class="tile-cap"><span>Specification first</span><strong>The right model, not a lookalike</strong></figcaption>
        </figure>
        <figure class="tile tile-b">
          <div class="tile-media"><img src="/static/images/desk.svg" alt="Illustration of a desk with a laptop and a notebook"></div>
          <figcaption class="tile-cap"><span>Price with proof</span><strong>Ranges, medians and spread</strong></figcaption>
        </figure>
        <figure class="tile tile-c">
          <div class="tile-media"><img src="/static/images/devices.svg" alt="Illustration of a phone, wireless earbuds and a smartwatch"></div>
          <figcaption class="tile-cap"><span>Beyond laptops</span><strong>Evidence for the device you&rsquo;re weighing up</strong></figcaption>
        </figure>
        <div class="tile tile-quote">
          <blockquote>&ldquo;A price means little until you know what it was measured against.&rdquo;</blockquote>
          <cite>The FORESEEN principle</cite>
        </div>
      </div>
    </div>
  </section>

  <section class="contrast">
    <div class="wrap">
      <div class="contrast-inner">
        <div class="contrast-copy">
          <p class="kicker">The idea</p>
          <h2>See beyond <em>the price.</em></h2>
          <p>A number on its own can&rsquo;t tell you if a used product is worth it. FORESEEN separates exact matches from uncertain listings and mismatches, then shows you the evidence behind every figure &mdash; so you buy with context instead of hope.</p>
        </div>
        <div class="contrast-art">
          <img src="/static/images/desk.svg" alt="Illustration of a workspace with a laptop and notes">
        </div>
      </div>
    </div>
  </section>

  <section class="how" id="how">
    <div class="wrap">
      <div class="how-head">
        <p class="kicker">How it works</p>
        <h2>Three steps, all of them visible</h2>
        <p>No black box. Each stage of the analysis is shown in the result.</p>
      </div>

      <div class="how-step">
        <div class="how-body">
          <p class="how-num">01</p>
          <h3>Describe the product</h3>
          <p>Type the model and specification you care about &mdash; chip, memory, storage and condition.</p>
        </div>
        <div class="how-media"><img src="/static/images/devices.svg" alt="Illustration of consumer electronics"></div>
      </div>

      <div class="how-step reverse">
        <div class="how-media"><img src="/static/images/desk.svg" alt="Illustration of a desk with a laptop"></div>
        <div class="how-body">
          <p class="how-num">02</p>
          <h3>Match the evidence</h3>
          <p>We isolate listings that match your exact specification and set the rest aside as context &mdash; never as proof.</p>
        </div>
      </div>

      <div class="how-step">
        <div class="how-body">
          <p class="how-num">03</p>
          <h3>See the picture</h3>
          <p>Review price ranges, spread and a transparent confidence signal before you decide.</p>
        </div>
        <div class="how-media"><img src="/static/images/hero-laptop.svg" alt="Illustration of a laptop showing price insights"></div>
      </div>
    </div>
  </section>

  <section class="cta">
    <div class="wrap">
      <div class="cta-inner">
        <h2>Start with a product you&rsquo;re considering</h2>
        <p>Enter the exact model and specification to see the evidence behind the price.</p>
        <a class="btn-primary" href="/#search">Analyze a product</a>
      </div>
    </div>
  </section>
</main>
"""

RESULT_BODY = """
<main class="results">
  <div class="wrap results-hero">
    <a class="back-link" href="/">&larr; New search</a>
    <div class="identity">
      <div class="identity-art"><img src="/static/images/hero-laptop.svg" alt="Product illustration"></div>
      <div class="identity-copy">
        <p class="kicker">Market analysis</p>
        <h1>{{ subject|e }}</h1>
        {% if origin == 'live' %}
          <span class="origin live"><span class="dot"></span>Live results from Google Shopping</span>
        {% elif origin == 'cache' %}
          <span class="origin cached"><span class="dot"></span>Cached market data</span>
        {% endif %}
        {% if empty %}
          <p>We couldn&rsquo;t line this search up with verifiable listings.</p>
        {% else %}
          <p>Price evidence for this product, built only from the listings we could verify.</p>
        {% endif %}
      </div>
    </div>
    {% if not empty %}
      <span class="status {% if result.status == 'insufficient_evidence' %}insufficient{% else %}preliminary{% endif %}">Result: {% if result.status == 'preliminary' %}Preliminary estimate{% else %}Not enough evidence yet{% endif %}</span>
    {% endif %}
  </div>
  <div class="wrap results-body">
    {% if empty %}
    <section class="empty">
      <div class="icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/></svg></div>
      {% if empty_reason == 'missing_credentials' %}
        <h2>Live lookup isn&rsquo;t available yet</h2>
        <p>FORESEEN can search live market listings, but this server has no SerpApi key configured, so it can only read products it has already cached. We never show results for a different product just to fill the page.</p>
        <p class="empty-hint">A cached example is available for the <strong>MacBook Air M1 8GB 256GB</strong>. To look up other products, add a <code>SERPAPI_API_KEY</code> to the server&rsquo;s <code>.env</code>.</p>
      {% elif empty_reason == 'api_error' %}
        <h2>The market lookup failed</h2>
        <p>We reached the listings provider but couldn&rsquo;t complete the search for &ldquo;{{ subject|e }}&rdquo;. This is usually temporary.</p>
        {% if error_detail %}<p class="empty-hint">{{ error_detail|e }}</p>{% endif %}
      {% elif empty_reason == 'empty_response' %}
        <h2>No listings matched this search</h2>
        <p>The provider returned no listings for &ldquo;{{ subject|e }}&rdquo;. Try a more specific model name, or add a specification such as storage or capacity.</p>
      {% elif empty_reason == 'no_evidence' %}
        <h2>Not enough matching evidence</h2>
        <p>We reached market listings, but none of them matched &ldquo;{{ subject|e }}&rdquo; closely enough to count as evidence. FORESEEN never substitutes a different product&rsquo;s data.</p>
      {% else %}
        <h2>No cached evidence available for this search</h2>
        <p>We couldn&rsquo;t find cached, verifiable listings for &ldquo;{{ subject|e }}&rdquo;. This is a data-availability issue rather than a problem with your search.</p>
        <p class="empty-hint">A cached example is available for the <strong>MacBook Air M1 8GB 256GB</strong>.</p>
      {% endif %}
      <a class="btn-primary" href="/">Try another search</a>
    </section>
    {% else %}
      {% if result.statistics and result.statistics.count %}
      <section class="insight-grid" aria-label="Price insights">
        <article class="insight primary span-5">
          <div class="label">Observed median price</div>
          <div class="value">{{ result.statistics.median|inr }}</div>
          <div class="sub">The middle price across matching listings</div>
        </article>
        <article class="insight span-3">
          <div class="label">Lowest observed</div>
          <div class="value">{{ result.statistics.minimum|inr }}</div>
          <div class="sub">Cheapest matching listing we found</div>
        </article>
        <article class="insight span-4">
          <div class="label">Highest observed</div>
          <div class="value">{{ result.statistics.maximum|inr }}</div>
          <div class="sub">Most expensive matching listing</div>
        </article>
        <article class="insight span-4">
          <div class="label">Price spread</div>
          <div class="value">{{ result.statistics.spread|inr }}</div>
          <div class="sub">Gap between the lowest and highest observed price</div>
        </article>
        <article class="insight span-4">
          <div class="label">Eligible observations</div>
          <div class="value">{{ result.statistics.count }}</div>
          <div class="sub">Exact-spec listings used in this estimate</div>
        </article>
        <article class="insight span-4">
          <div class="label">Confidence level</div>
          <div class="value"><span class="badge {% if result.statistics.confidence == 'high' %}high{% else %}low{% endif %}">{{ result.statistics.confidence|capitalize }}</span></div>
          <div class="sub">{% if result.statistics.confidence == 'high' %}Five or more matching listings{% else %}Fewer than five matching listings{% endif %}</div>
        </article>
      </section>
      <section class="panel explain">
        <h3>What this means</h3>
        <p><strong>Preliminary estimate.</strong> Only {{ result.statistics.count }} matching listing{{ '' if result.statistics.count == 1 else 's' }} found that state every attribute you searched for. Treat this as a directional guide, not a guaranteed value, because market prices move quickly.</p>
        {% if result.statistics.confidence != 'high' %}
        <p><strong>Limited evidence &mdash; compare carefully before buying.</strong> With only {{ result.statistics.count }} matching listing{{ '' if result.statistics.count == 1 else 's' }}, the median can shift as soon as new listings appear. More matching listings would give a firmer picture.</p>
        {% endif %}
        <p>The middle half of matching listings falls between {{ result.statistics.q1|inr }} and {{ result.statistics.q3|inr }}, and the gap between the lowest and highest observed price is {{ result.statistics.spread|inr }}.</p>
      </section>
      {% else %}
      <section class="panel explain">
        <h3>Not enough evidence yet</h3>
        <p>We found fewer than three exact-spec listings, so FORESEEN won&rsquo;t publish a price estimate &mdash; showing a firm number here would overstate what the evidence supports.</p>
        {% if result.available_prices %}
        <p>Only {{ result.available_prices|length }} matching listing{{ '' if result.available_prices|length == 1 else 's' }} found. Here {{ 'is the price' if result.available_prices|length == 1 else 'are the prices' }} we did find:</p>
        <div class="price-chips">{% for p in result.available_prices %}<span class="price-chip">{{ p|inr }}</span>{% endfor %}</div>
        {% endif %}
      </section>
      {% endif %}
    {% endif %}
    {% if avail and avail.show %}
    <section class="lens" aria-label="Availability Lens">
      <div class="lens-head">
        <h2>Availability Lens</h2>
        <p>How the eligible prices this search returned are spread out, and how the listings you see first compare with all of them.</p>
      </div>

      <div class="lens-cards">
        <div class="lens-card2 first">
          <div class="k">Middle observed price</div>
          <div class="big">{% if avail.median is not none %}{{ avail.median|inr }}{% else %}&mdash;{% endif %}<span class="unit">{{ avail.median_label if avail.median is not none else 'no price' }}</span></div>
          <div class="meta">{{ avail.count }} eligible listing{{ '' if avail.count == 1 else 's' }} with a price</div>
        </div>
        <div class="lens-card2">
          <div class="k">Eligible listings</div>
          <div class="big">{{ avail.count }}<span class="unit">with a price</span></div>
          <div class="meta">{% if avail.has_prices %}Prices from {{ avail.minimum|inr }} to {{ avail.maximum|inr }}{% else %}No usable price was found{% endif %}</div>
        </div>
      </div>

      <div class="lens-range">{{ avail.range_explanation|safe }}</div>

      <div class="scale-card">
        <div class="scale-head">
          <span class="scale-title">Every eligible price on one scale</span>
          <span class="scale-sub">{% if avail.has_prices %}{{ avail.count }} listing{{ '' if avail.count == 1 else 's' }} shown{% else %}no priced listings{% endif %}</span>
        </div>
        {% if avail.has_prices %}
        <div class="scale-track">
          <span class="scale-line"></span>
          {% for d in avail.dots %}<span class="scale-dot" style="left:{{ d.pos }}%" title="{{ d.label }}{% if d.count > 1 %} &middot; {{ d.count }} listings{% endif %}"></span>{% endfor %}
          <span class="scale-cap" style="left:{{ avail.min_pos }}%"></span>
          <span class="scale-cap" style="left:{{ avail.max_pos }}%"></span>
          {% if not avail.single %}<span class="scale-median" style="left:{{ avail.median_pos }}%"></span>
          <span class="scale-tag {{ avail.median_align }}" style="left:{{ avail.median_pos }}%">{{ avail.median|inr }} &middot; {{ avail.median_label }}</span>
          {% else %}<span class="scale-median" style="left:{{ avail.median_pos }}%"></span>{% endif %}
        </div>
        <div class="scale-axis">
          {% if avail.single %}<span class="tick center">{{ avail.minimum|inr }}</span>
          {% else %}<span class="tick left">{{ avail.minimum|inr }}</span><span class="tick right">{{ avail.maximum|inr }}</span>{% endif %}
        </div>
        {% else %}
        <p class="scale-none">No eligible listing carried a usable price, so there is nothing to place on the scale.</p>
        {% endif %}
      </div>

      {% if avail.compact %}
      <details class="lens-zoom">
        <summary>See a zoomed view (the full range stays above)</summary>
        <div class="scale-track">
          <span class="scale-line"></span>
          {% for d in avail.compact.dots %}<span class="scale-dot" style="left:{{ d.pos }}%" title="{{ d.label }}{% if d.count > 1 %} &middot; {{ d.count }} listings{% endif %}"></span>{% endfor %}
          <span class="scale-median" style="left:{{ avail.compact.median_pos }}%"></span>
        </div>
        <div class="scale-axis">
          <span class="tick left">{{ avail.compact.lo_label }}</span>
          <span class="tick right">{{ avail.compact.hi_label }}</span>
        </div>
        <p class="zoom-note">Zoomed to the central range so the bulk of prices is easier to read. {{ avail.compact.excluded }} listing{{ '' if avail.compact.excluded == 1 else 's' }} sit outside this view (up to {{ avail.compact.outside_max }}); the full scale above is unchanged and nothing is hidden.</p>
      </details>
      {% endif %}

      <div class="lens-meaning">
        <h3>What this means</h3>
        <ul>
          {% for line in avail.insights %}<li>{{ line }}</li>{% endfor %}
        </ul>
      </div>

      <div class="lens-compare">
        <h3>First page vs all eligible listings</h3>
        <p class="compare-note">The first-page listings are included in the broader set, so the two groups overlap and are not independent samples.</p>
        <div class="compare-grid">
          <div class="compare-item first">
            <div class="k">Seen first</div>
            <div class="v">{% if avail.first.has_stats %}{{ avail.first.median|inr }}{% if not avail.first.single %}<span class="u">median</span>{% else %}<span class="u">one listing</span>{% endif %}{% else %}&mdash;<span class="u">no price</span>{% endif %}</div>
            <div class="m">{{ avail.first.priced_count }} eligible listing{{ '' if avail.first.priced_count == 1 else 's' }} on the first page</div>
          </div>
          <div class="compare-item">
            <div class="k">All eligible listings</div>
            <div class="v">{% if avail.broader.has_stats %}{{ avail.broader.median|inr }}<span class="u">median</span>{% else %}&mdash;<span class="u">no price</span>{% endif %}</div>
            <div class="m">{{ avail.broader.priced_count }} eligible listing{{ '' if avail.broader.priced_count == 1 else 's' }} in total</div>
          </div>
        </div>
        <p class="compare-result">{{ avail.difference_text }}</p>
      </div>

      <details class="lens-details">
        <summary>How is this calculated?</summary>
        <dl class="details-stats">
          <div><dt>Eligible listings</dt><dd>{{ avail.count }}</dd></div>
          <div><dt>Lowest</dt><dd>{% if avail.has_prices %}{{ avail.minimum|inr }}{% else %}&mdash;{% endif %}</dd></div>
          <div><dt>Highest</dt><dd>{% if avail.has_prices %}{{ avail.maximum|inr }}{% else %}&mdash;{% endif %}</dd></div>
          <div><dt>Median</dt><dd>{% if avail.median is not none %}{{ avail.median|inr }}{% else %}&mdash;{% endif %}</dd></div>
          {% if avail.has_quartiles %}<div><dt>Lower quartile (25%)</dt><dd>{{ avail.q1|inr }}</dd></div><div><dt>Upper quartile (75%)</dt><dd>{{ avail.q3|inr }}</dd></div>{% endif %}
          <div><dt>Confidence</dt><dd>Low</dd></div>
          <div><dt>First page</dt><dd>{{ avail.first.listing_count }} of {{ avail.listing_count }} eligible listing{{ '' if avail.listing_count == 1 else 's' }}</dd></div>
        </dl>
        <p class="details-limits">{{ avail.limitations }}</p>
        {% if avail.links %}
        <div class="details-links">
          <h4>Listings behind this view</h4>
          <ul>
            {% for it in avail.links %}<li><a href="{{ it.url }}" target="_blank" rel="noopener">{{ it.title }}</a>{% if it.price is not none %} &mdash; {{ it.price|inr }}{% endif %}{% if it.rank %} <span class="rank">(rank {{ it.rank }})</span>{% endif %}</li>{% endfor %}
          </ul>
        </div>
        {% endif %}
      </details>
    </section>
    {% endif %}
    {% if result.evidence and total_evidence %}
    <section class="evidence-wrap">
      <div class="evidence-intro">
        <h2>Evidence we examined</h2>
        <p>Every listing is sorted into a group and kept separate, so nothing is presented as more certain than it is.</p>
      </div>
      {% for section in sections %}
        {% if section['items'] %}
        <div class="evidence-section">
          <div class="evidence-head">
            <h3>{{ section['title'] }}</h3>
            <span class="count">{{ section['items']|length }} listing{{ '' if section['items']|length == 1 else 's' }}</span>
          </div>
          <p class="evidence-blurb">{{ section['blurb'] }}</p>
          <div class="listing-grid">
            {% for it in section['items'] %}
            <article class="listing">
              <div class="top">
                <span class="badge {{ section['badge_class'] }}">{{ section['badge'] }}</span>
                <span class="price">{{ it.price|inr }}</span>
              </div>
              <p class="title">{{ it.title }}</p>
              <div class="meta">
                <span><span class="k">Seller:</span> {{ it.source if it.source else 'Unknown' }}</span>
                <span><span class="k">Condition:</span> {{ it.condition if it.condition else 'Unknown' }}</span>
              </div>
              {% if it.exclusion %}
              <p class="exclusion"><span class="k">Why it&rsquo;s excluded:</span> {{ it.exclusion }}</p>
              {% endif %}
              {% if it.url %}
              <a class="link" href="{{ it.url }}" target="_blank" rel="noopener">View original listing &rarr;</a>
              {% else %}
              <span class="link no-link">No original link available</span>
              {% endif %}
            </article>
            {% endfor %}
          </div>
        </div>
        {% endif %}
      {% endfor %}
    </section>
    {% endif %}
    <p><a class="link-back" href="/">&larr; New search</a></p>
  </div>
</main>
"""

HTML_TEMPLATE = PAGE_HEAD + NAV + HOME_BODY + FOOTER + SCRIPTS + "</body>\n</html>\n"
RESULT_TEMPLATE = PAGE_HEAD + NAV + RESULT_BODY + FOOTER + SCRIPTS + "</body>\n</html>\n"


def _render_empty(subject, reason, detail=None):
    """Render a friendly empty/error result page (never an unrelated fallback)."""
    return render_template_string(
        RESULT_TEMPLATE,
        result=None,
        subject=subject,
        empty=True,
        empty_reason=reason,
        error_detail=detail,
        origin=None,
        sections=[],
        total_evidence=0,
        avail=None,
    )


@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML_TEMPLATE, query='')


@app.route('/analyze', methods=['GET', 'POST'])
def analyze():
    if request.method == 'GET':
        # Render the home page for GET requests
        return render_template_string(HTML_TEMPLATE, query='')

    query = request.form.get('query', '').strip()
    if not query:
        return render_template_string(HTML_TEMPLATE, query='')

    cache_dir = Path(__file__).resolve().parent.parent / 'cache'
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = analyze_query(cache_dir=cache_dir, query=query)
    except Exception as e:  # defensive: surface a helpful message, never a 500
        return _render_empty(query, 'error', detail=str(e))

    if result.get('error'):
        return _render_empty(query, result.get('error'), detail=result.get('detail'))

    result.setdefault('statistics', {})
    result.setdefault('evidence', {})
    eligible = result.get('summary', {}).get('eligible_price_count', 0)
    sections = _build_evidence_sections(result)
    total_evidence = sum(len(section['items']) for section in sections)
    # The Availability Lens is derived entirely from the same result data; it
    # makes no further API calls and never invents a price.
    avail = _build_availability_view(result.get('availability'), result)
    # Only treat the search as empty when there is genuinely nothing to show.
    # If listings were classified (matches, near-misses or exclusions) we still
    # render the evidence page so the reasons stay visible.
    empty = (eligible == 0 and total_evidence == 0)
    return render_template_string(
        RESULT_TEMPLATE,
        result=result,
        subject=query,
        empty=empty,
        empty_reason=('no_evidence' if empty else ''),
        error_detail=None,
        origin=result.get('origin'),
        sections=sections,
        total_evidence=total_evidence,
        avail=avail,
    )


if __name__ == '__main__':
    # Run on a local development port.
    app.run(host='0.0.0.0', port=8000, debug=True)
