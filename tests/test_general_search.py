"""Generalized, product-agnostic behaviour for FORESEEN.

These tests are fully offline: external SerpApi calls are mocked, so no real
network requests are made.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import shopping
from backend.price_estimator import analyze_query, estimate_price


def write_cache(cache_dir, query, listings, engine="google_shopping", ts="20260101T000000Z"):
    payload = {
        "query": query,
        "engine": engine,
        "timestamp": ts,
        "response": {"shopping_results": listings},
    }
    safe = "_".join(query.split())
    path = Path(cache_dir) / f"{engine}_{safe}_{ts}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def item(title, price, **extra):
    d = {
        "title": title,
        "extracted_price": price,
        "source": "shop.example",
        "product_link": "http://example.com/x",
    }
    d.update(extra)
    return d


class CategoryMatchingTests(unittest.TestCase):
    def cls(self, query, title):
        return shopping.classify_item({"title": title}, shopping.build_spec(query))

    def test_iphone(self):
        self.assertEqual(self.cls("iPhone 13 128GB", "Apple iPhone 13 128GB"), "confirmed")
        self.assertEqual(self.cls("iPhone 13 128GB", "Apple iPhone 13"), "ambiguous")
        self.assertEqual(self.cls("iPhone 13 128GB", "Apple iPhone 12 128GB"), "mismatch")

    def test_gpu(self):
        self.assertEqual(
            self.cls("NVIDIA RTX 3080 10GB", "NVIDIA GeForce RTX 3080 10GB"),
            "confirmed",
        )
        self.assertEqual(
            self.cls("NVIDIA RTX 3080 10GB", "NVIDIA GeForce RTX 3080 Graphics Card"),
            "ambiguous",
        )
        self.assertEqual(
            self.cls("NVIDIA RTX 3080 10GB", "NVIDIA GeForce RTX 3070 10GB"),
            "mismatch",
        )

    def test_camera(self):
        self.assertEqual(
            self.cls("Canon EOS R6", "Canon EOS R6 Mirrorless Digital Camera Body"),
            "confirmed",
        )
        self.assertEqual(
            self.cls("Canon EOS R6", "Canon EOS R5 Mirrorless Camera"), "mismatch"
        )

    def test_headphones_join_and_plural(self):
        self.assertEqual(
            self.cls("Sony WH-1000XM4 headphones", "Sony WH1000XM4 Wireless Headphone"),
            "confirmed",
        )
        self.assertEqual(
            self.cls("Sony WH-1000XM4", "Sony WH-1000XM3 Wireless Headphones"),
            "mismatch",
        )

    def test_missing_specs_is_conservative(self):
        # No storage asked for -> identity match with extra specs is confirmed.
        self.assertEqual(self.cls("MacBook Air", "Apple MacBook Air M1 8GB 256GB"), "confirmed")
        # A required spec is missing -> only uncertain, never exact.
        self.assertEqual(self.cls("MacBook Air M1 8GB 256GB", "MacBook Air M1"), "ambiguous")

    def test_variant_is_not_exact(self):
        self.assertEqual(self.cls("iPhone 13", "Apple iPhone 13 Pro Max 128GB"), "ambiguous")

    def test_legacy_default_behaviour_preserved(self):
        # One-argument classify_item keeps the historical MacBook behaviour.
        self.assertEqual(
            shopping.classify_item(
                {"title": "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB SSD"}
            ),
            "confirmed",
        )
        self.assertEqual(shopping.classify_item({"title": "Apple MacBook Air"}), "ambiguous")
        self.assertEqual(
            shopping.classify_item({"title": "MacBook Pro M1 8GB 256GB"}), "mismatch"
        )


class ApiKeyConfigTests(unittest.TestCase):
    """The collector and app must agree on the key variable name and path."""

    def test_canonical_env_name_is_used(self):
        with mock.patch.object(shopping, "load_env"), mock.patch.dict(
            os.environ, {"SERPAPI_API_KEY": "canonical-key"}, clear=True
        ):
            self.assertEqual(shopping.get_api_key(), "canonical-key")
            self.assertTrue(shopping.has_api_key())

    def test_legacy_env_name_still_supported(self):
        with mock.patch.object(shopping, "load_env"), mock.patch.dict(
            os.environ, {"SERPAPI_KEY": "legacy-key"}, clear=True
        ):
            self.assertEqual(shopping.get_api_key(), "legacy-key")
            self.assertTrue(shopping.has_api_key())

    def test_canonical_takes_precedence_over_legacy(self):
        with mock.patch.object(shopping, "load_env"), mock.patch.dict(
            os.environ,
            {"SERPAPI_API_KEY": "canonical", "SERPAPI_KEY": "legacy"},
            clear=True,
        ):
            self.assertEqual(shopping.get_api_key(), "canonical")

    def test_missing_key_reported(self):
        with mock.patch.object(shopping, "load_env"), mock.patch.dict(
            os.environ, {}, clear=True
        ):
            self.assertIsNone(shopping.get_api_key(required=False))
            self.assertFalse(shopping.has_api_key())
            with self.assertRaises(shopping.SerpApiError):
                shopping.get_api_key()

    def test_env_path_is_absolute_and_based_on_file(self):
        path = shopping._env_path()
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.name, ".env")
        self.assertEqual(path.parent, Path(shopping.__file__).resolve().parent.parent)

    def test_network_error_never_leaks_key(self):
        boom = shopping.requests.exceptions.RequestException(
            "https://serpapi.com/search.json?api_key=SECRET123 timed out"
        )
        with mock.patch.object(
            shopping, "get_api_key", return_value="SECRET123"
        ), mock.patch.object(shopping.requests, "get", side_effect=boom):
            with self.assertRaises(shopping.SerpApiError) as ctx:
                shopping.fetch_shopping("iPhone 13 128GB")
        self.assertNotIn("SECRET123", str(ctx.exception))


class CacheIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write_cache(
            self.tmp,
            "MacBook Air M1 8GB 256GB",
            [item("Apple MacBook Air with M1 Chip 8GB 256GB", 50000)],
        )
        write_cache(
            self.tmp,
            "Sony WH-1000XM4",
            [item("Sony WH-1000XM4 Wireless Headphones", 20000)],
        )

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_condition_and_brand_variants_share_cache(self):
        resp = shopping.load_cached_for_query(
            self.tmp, "Apple MacBook Air M1 8GB 256GB used"
        )
        self.assertIsNotNone(resp)
        titles = [r["title"] for r in resp["shopping_results"]]
        self.assertTrue(all("MacBook" in t for t in titles))

    def test_distinct_queries_are_isolated(self):
        mac = shopping.load_cached_for_query(self.tmp, "MacBook Air M1 8GB 256GB")
        sony = shopping.load_cached_for_query(self.tmp, "Sony WH-1000XM4")
        self.assertIn("MacBook", mac["shopping_results"][0]["title"])
        self.assertIn("WH-1000XM4", sony["shopping_results"][0]["title"])

    def test_unrelated_query_never_falls_back_to_macbook(self):
        result = analyze_query(cache_dir=self.tmp, query="Canon EOS R6", allow_live=False)
        self.assertEqual(result.get("error"), "no_cache")
        self.assertNotIn("MacBook", json.dumps(result))

    def test_estimate_uses_requested_query_only(self):
        result = estimate_price(cache_dir=self.tmp, query="Sony WH-1000XM4")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertNotIn("MacBook", json.dumps(result["evidence"]))


class LiveLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_missing_credentials(self):
        with mock.patch.object(shopping, "has_api_key", return_value=False):
            result = analyze_query(cache_dir=self.tmp, query="iPhone 15 128GB")
        self.assertEqual(result.get("error"), "missing_credentials")

    def test_api_error_is_reported(self):
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", side_effect=shopping.SerpApiError("boom")
        ):
            result = analyze_query(cache_dir=self.tmp, query="iPhone 15 128GB")
        self.assertEqual(result.get("error"), "api_error")
        self.assertIn("boom", result.get("detail", ""))

    def test_empty_response_is_not_cached(self):
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", return_value={"shopping_results": []}
        ):
            result = analyze_query(cache_dir=self.tmp, query="iPhone 15 128GB")
        self.assertEqual(result.get("error"), "empty_response")
        self.assertEqual(list(self.tmp.glob("*.json")), [])

    def test_successful_live_search_is_cached_and_reused(self):
        data = {"shopping_results": [item("Sony WH-1000XM4 Wireless Headphones", 21000)]}
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", return_value=data
        ) as fetch:
            result = analyze_query(cache_dir=self.tmp, query="Sony WH-1000XM4")
        fetch.assert_called_once_with("Sony WH-1000XM4")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result.get("origin"), "live")
        # The successful response was persisted; a second call reuses the cache.
        with mock.patch.object(
            shopping, "fetch_shopping", side_effect=AssertionError("should not refetch")
        ):
            again = analyze_query(cache_dir=self.tmp, query="Sony WH-1000XM4")
        self.assertEqual(again.get("origin"), "cache")

    def test_insufficient_evidence_excludes_uncertain_and_mismatch(self):
        listings = [
            item("Apple iPhone 15 128GB", 60000),   # confirmed
            item("Apple iPhone 15 256GB", 70000),   # ambiguous (different storage)
            item("Apple iPhone 14 128GB", 45000),   # mismatch (different model)
        ]
        write_cache(self.tmp, "iPhone 15 128GB", listings)
        result = estimate_price(cache_dir=self.tmp, query="iPhone 15 128GB")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["confirmed"], 1)
        self.assertEqual(result["summary"]["eligible_price_count"], 1)


class AccessoryRelevanceTests(unittest.TestCase):
    """Cases, covers, protectors and spare parts must never count as the product."""

    def cls(self, query, title):
        return shopping.classify_item({"title": title}, shopping.build_spec(query))

    def test_samsung_a17_phone_is_confirmed(self):
        self.assertEqual(
            self.cls("samsung A17", "Samsung Galaxy A17 5G (Black, 6GB-128GB)"),
            "confirmed",
        )

    def test_samsung_a17_cases_and_covers_are_accessories(self):
        for title in (
            "Skyro Back Case Cover for Samsung Galaxy A17 5G | Compatible for Samsung",
            "Its Me Personalised Samsung A17 5G Back Cover - dreamy",
            "Smartlike Flip Cover For Samsung Galaxy A17 5g",
            "for Samsung Galaxy A17 5G / A17 4G Case TPU + PC Shockproof Clear Cover",
            "BTH - Huelle fuer Samsung Galaxy A17 - Bookcase Etui",
        ):
            self.assertEqual(self.cls("samsung A17", title), "accessory", title)

    def test_samsung_a17_screen_protectors_and_parts_are_accessories(self):
        for title in (
            "Samsung Galaxy A17 5G LCD Screen Display With Frame Black - ORIGINAL",
            "Samsung Galaxy A17 5G ORIGINAL LCD Display - Black",
            "Tempered Glass Screen Protector for Samsung Galaxy A17 5G",
            "Anonbasics Samsung A17 Back Panel",
            "Samsung Galaxy A17 5G User Manual: Step-by-Step Guide",
        ):
            self.assertEqual(self.cls("samsung A17", title), "accessory", title)

    def test_different_model_is_a_mismatch_not_an_accessory(self):
        self.assertEqual(self.cls("samsung A17", "Samsung Galaxy M17 5G"), "mismatch")
        self.assertEqual(self.cls("samsung A17", "Samsung Galaxy A15 5G"), "mismatch")
        self.assertEqual(
            self.cls("Apple iPhone 13 128GB", "Apple iPhone 12 128GB"), "mismatch"
        )

    def test_unrelated_categories_match_or_exclude_correctly(self):
        self.assertEqual(
            self.cls("Canon EOS R6", "Canon EOS R6 Mirrorless Digital Camera Body"),
            "confirmed",
        )
        self.assertEqual(
            self.cls("Canon EOS R6", "Canon EOS R6 Camera Bag Case"), "accessory"
        )
        self.assertEqual(
            self.cls("Sony WH-1000XM4", "Sony WH-1000XM4 Replacement Ear Pads"),
            "accessory",
        )
        self.assertEqual(
            self.cls("NVIDIA RTX 3080 10GB", "NVIDIA GeForce RTX 3070 10GB"), "mismatch"
        )

    def test_ambiguous_titles_and_missing_specs(self):
        # Right model, but the requested storage is absent -> uncertain only.
        self.assertEqual(
            self.cls("Samsung Galaxy A17 128GB", "Samsung Galaxy A17 5G"), "ambiguous"
        )
        self.assertEqual(self.cls("Apple iPhone 13 128GB", "Apple iPhone 13"), "ambiguous")
        # No specification was requested, so a plain model title is exact.
        self.assertEqual(self.cls("Samsung Galaxy A17", "Samsung Galaxy A17 5G"), "confirmed")

    def test_searching_for_an_accessory_still_works(self):
        # The accessory word is part of the *query*, so it must not be excluded.
        self.assertEqual(self.cls("iPhone 13 case", "Apple iPhone 13 Clear Case"), "confirmed")
        self.assertEqual(
            self.cls(
                "iPhone 13 screen protector",
                "iPhone 13 Tempered Glass Screen Protector",
            ),
            "confirmed",
        )

    def test_legacy_macbook_matching_unchanged(self):
        self.assertEqual(
            self.cls(
                "MacBook Air M1 8GB 256GB used",
                "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB SSD",
            ),
            "confirmed",
        )
        self.assertEqual(
            self.cls("MacBook Air M1 8GB 256GB used", "Apple MacBook Air with M1 Chip 256GB"),
            "ambiguous",
        )
        self.assertEqual(
            self.cls(
                "MacBook Air M1 8GB 256GB used",
                "Apple MacBook Air with Intel Core i5 8GB 256GB",
            ),
            "mismatch",
        )


class EvidenceQualityTests(unittest.TestCase):
    """Only genuine products may enter the price statistics."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_accessory_only_search_reports_insufficient_evidence(self):
        listings = [
            item("Skyro Back Case Cover for Samsung Galaxy A17 5G", 149),
            item("Samsung Galaxy A17 5G LCD Screen Display With Frame", 1899),
            item("Samsung Galaxy A17 5G User Manual Step-by-Step Guide", 449),
            item("Tempered Glass Screen Protector for Samsung Galaxy A17 5G", 99),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 0)
        self.assertEqual(result["summary"]["accessories"], 4)
        self.assertEqual(len(result["evidence"]["accessories"]), 4)

    def test_low_priced_genuine_listing_is_not_rejected_by_price(self):
        listings = [
            item("Apple iPhone 13 128GB", 500),  # genuine but unusually cheap
            item("Apple iPhone 13 128GB", 60000),
            item("Apple iPhone 13 128GB", 61000),
        ]
        write_cache(self.tmp, "iPhone 13 128GB", listings)
        result = estimate_price(cache_dir=self.tmp, query="iPhone 13 128GB")
        self.assertEqual(result["status"], "preliminary")
        self.assertEqual(result["summary"]["eligible_price_count"], 3)
        self.assertEqual(result["statistics"]["minimum"], 500)

    def test_accessories_excluded_but_genuine_prices_kept(self):
        listings = [
            item("Samsung Galaxy A17 5G (Black, 6GB-128GB)", 20000),
            item("Samsung Galaxy A17 5G (6GB-128GB)", 21000),
            item("Samsung Galaxy A17 5G (6GB-128GB)", 22000),
            item("Samsung Galaxy A17 5G Back Cover", 99),
            item("Samsung Galaxy A17 5G LCD Screen Display", 4999),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result["summary"]["confirmed"], 3)
        self.assertEqual(result["summary"]["accessories"], 2)
        self.assertEqual(result["summary"]["eligible_price_count"], 3)
        self.assertEqual(result["statistics"]["minimum"], 20000)
        self.assertEqual(result["statistics"]["maximum"], 22000)

    def test_aggregated_accessories_never_counted(self):
        listings = [
            item("Samsung Galaxy A17 5G Back Cover", 149, multiple_sources=True),
            item("Samsung Galaxy A17 5G Back Cover", 179, multiple_sources=True),
            item("Samsung Galaxy A17 5G LCD Screen Display", 4999),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 0)

    def test_live_accessory_results_are_excluded(self):
        data = {
            "shopping_results": [
                item("Skyro Back Case Cover for Samsung Galaxy A17 5G", 149),
                item("Samsung Galaxy A17 5G ORIGINAL LCD Display", 4999),
            ]
        }
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", return_value=data
        ):
            result = analyze_query(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result.get("origin"), "live")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 0)
        self.assertEqual(result["summary"]["accessories"], 2)


class SamsungA17Tests(unittest.TestCase):
    """Balance check: the A17 phone must match without over- or under-filtering."""

    def cls(self, query, title):
        return shopping.classify_item({"title": title}, shopping.build_spec(query))

    def test_phone_is_a_strong_match_without_repeating_query_specs(self):
        # Query asks for no storage/condition, so extra specs in the title are fine.
        self.assertEqual(self.cls("samsung A17", "Samsung Galaxy A17 5G 128GB"), "confirmed")
        self.assertEqual(
            self.cls("samsung A17", "Samsung Galaxy A17 5g ( Black, 6GB-128GB )"),
            "confirmed",
        )
        self.assertEqual(
            self.cls("Samsung A17 128GB", "Samsung Galaxy A17 5G 128GB"), "confirmed"
        )

    def test_cases_and_screen_protectors_are_accessories(self):
        self.assertEqual(
            self.cls("samsung A17", "Skyro Back Case Cover for Samsung Galaxy A17 5G"),
            "accessory",
        )
        self.assertEqual(
            self.cls("samsung A17", "Tempered Glass Screen Protector for Samsung A17 5G"),
            "accessory",
        )
        self.assertEqual(
            self.cls("samsung A17", "Samsung Galaxy A17 5G LCD Display GH82-38075A"),
            "accessory",
        )

    def test_different_samsung_model_is_a_mismatch(self):
        self.assertEqual(self.cls("samsung A17", "Samsung Galaxy M17 5G"), "mismatch")
        self.assertEqual(self.cls("samsung A17", "Samsung Galaxy A15 5G"), "mismatch")

    def test_missing_specification_is_ambiguous_not_rejected(self):
        # The query asks for 128GB but the listing does not state any storage.
        self.assertEqual(
            self.cls("Samsung A17 128GB", "Samsung Galaxy A17 5G"), "ambiguous"
        )

    def test_5g_is_enforced_only_when_it_conflicts(self):
        self.assertEqual(self.cls("Samsung A17 5G", "Samsung Galaxy A17 4G"), "mismatch")
        # Silent about the technology -> uncertain, never an automatic rejection.
        self.assertEqual(self.cls("Samsung A17 5G", "Samsung Galaxy A17"), "ambiguous")
        self.assertEqual(
            self.cls("Samsung A17 5G", "Samsung Galaxy A17 5G 128GB"), "confirmed"
        )

    def test_macbook_matching_is_preserved(self):
        self.assertEqual(
            self.cls(
                "MacBook Air M1 8GB 256GB used",
                "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB SSD",
            ),
            "confirmed",
        )
        self.assertEqual(
            self.cls("MacBook Air M1 8GB 256GB used", "Apple MacBook Air with M1 Chip 256GB"),
            "ambiguous",
        )
        self.assertEqual(
            self.cls(
                "MacBook Air M1 8GB 256GB used",
                "Apple MacBook Air with Intel Core i5 8GB 256GB",
            ),
            "mismatch",
        )


class AggregatedEligibilityTests(unittest.TestCase):
    """A strong match must count even when it is only available aggregated."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_aggregated_only_match_is_eligible_and_visible(self):
        listings = [
            item(
                "Samsung Galaxy A17 5G (Black, 6GB-128GB)",
                22000,
                multiple_sources=True,
                product_id="p-a17",
            ),
            item("Samsung Galaxy A17 5G Back Cover", 149),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result["summary"]["eligible_price_count"], 1)
        self.assertEqual(result["summary"]["aggregated_used"], 1)
        self.assertEqual(result["available_prices"], [22000])
        # The match stays visible in the evidence, not hidden behind a dead-end.
        self.assertEqual(len(result["evidence"]["aggregated"]), 1)
        self.assertEqual(result["summary"]["accessories"], 1)

    def test_aggregated_duplicate_of_independent_is_not_double_counted(self):
        listings = [
            item("Apple MacBook Air M1 8GB 256GB", 56000, multiple_sources=True, product_id="m"),
            item("Apple MacBook Air M1 8GB 256GB", 55000, product_id="m"),
        ]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        result = estimate_price(cache_dir=self.tmp, query="MacBook Air M1 8GB 256GB")
        self.assertEqual(result["summary"]["eligible_price_count"], 1)
        self.assertEqual(result["summary"]["aggregated"], 1)


class OriginStatusTests(unittest.TestCase):
    """The live-versus-cache badge must follow the actual data source."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_first_request_is_live_then_served_from_cache(self):
        data = {"shopping_results": [item("Samsung Galaxy A17 5G", 22000)]}
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", return_value=data
        ) as fetch:
            first = analyze_query(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(first.get("origin"), "live")
        self.assertEqual(fetch.call_count, 1)
        # The next identical request must be served from the saved cache.
        with mock.patch.object(
            shopping, "fetch_shopping", side_effect=AssertionError("should not refetch")
        ):
            second = analyze_query(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(second.get("origin"), "cache")

    def test_no_cache_and_no_live_is_reported_without_origin(self):
        result = analyze_query(cache_dir=self.tmp, query="samsung A17", allow_live=False)
        self.assertEqual(result.get("error"), "no_cache")
        self.assertIsNone(result.get("origin"))


class AggregatedListingTests(unittest.TestCase):
    def test_aggregated_never_counted_as_confirmed(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            listings = [
                item("Apple MacBook Air M1 8GB 256GB", 55000, multiple_sources=True),
                item("Apple MacBook Air M1 8GB 256GB", 56000, multiple_sources=True),
                item("Apple MacBook Air M1 8GB 256GB", 57000),
            ]
            write_cache(tmp, "MacBook Air M1 8GB 256GB", listings)
            result = estimate_price(cache_dir=tmp, query="MacBook Air M1 8GB 256GB")
            self.assertEqual(result["summary"]["aggregated"], 2)
            self.assertEqual(result["summary"]["eligible_price_count"], 1)
            self.assertEqual(result["status"], "insufficient_evidence")
        finally:
            for p in tmp.rglob("*"):
                p.unlink()
            tmp.rmdir()


class MultiSourceRoutingTests(unittest.TestCase):
    """Multi-source listings must be shown under their true classification.

    The aggregated "verified matches" group may only ever contain genuine
    product matches -- a multi-source mismatch or accessory belongs in its own
    (excluded) section so certainty is never overstated.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_routes_matches_mismatches_and_accessories_separately(self):
        listings = [
            item("Samsung Galaxy A17 5G (Black, 6GB-128GB)", 22000,
                 multiple_sources=True, product_id="a17"),
            item("Samsung Galaxy M17 5G", 21969,
                 multiple_sources=True, product_id="m17"),
            item("Samsung Galaxy A17 5G Back Cover", 599,
                 multiple_sources=True, product_id="cover"),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17")
        self.assertEqual(result["summary"]["aggregated"], 1)
        self.assertEqual(len(result["evidence"]["aggregated"]), 1)
        self.assertEqual(len(result["evidence"]["mismatches"]), 1)
        self.assertEqual(len(result["evidence"]["accessories"]), 1)
        # Only a genuine match may sit in the aggregated group.
        for it in result["evidence"]["aggregated"]:
            self.assertIsNone(it["exclusion"])

    def test_every_excluded_listing_carries_a_reason(self):
        listings = [
            item("Samsung Galaxy A17 5G (Black, 6GB-128GB)", 20000),
            item("Samsung Galaxy A17 5G", 21000),          # ambiguous: no storage
            item("Samsung Galaxy M17 5G", 19000),          # mismatch
            item("Samsung Galaxy A17 5G Back Cover", 99),  # accessory
        ]
        write_cache(self.tmp, "samsung A17 128GB", listings)
        result = estimate_price(cache_dir=self.tmp, query="samsung A17 128GB")
        for section in ("ambiguous", "mismatches", "accessories"):
            self.assertTrue(result["evidence"][section], section)
            for it in result["evidence"][section]:
                self.assertTrue(it["exclusion"], section)
                self.assertTrue(it["classification"], section)
        for it in result["evidence"]["confirmed"]:
            self.assertIsNone(it["exclusion"])


class CachePreservationTests(unittest.TestCase):
    """A failed live request must never damage an existing valid cache."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write_cache(
            self.tmp,
            "Sony WH-1000XM4",
            [item("Sony WH-1000XM4 Wireless Headphones", 20000)],
        )

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_cached_query_is_served_without_any_live_request(self):
        with mock.patch.object(
            shopping, "fetch_shopping", side_effect=AssertionError("should not fetch")
        ):
            result = analyze_query(cache_dir=self.tmp, query="Sony WH-1000XM4")
        self.assertEqual(result.get("origin"), "cache")

    def test_failed_live_request_leaves_existing_cache_intact(self):
        before = sorted(p.name for p in self.tmp.glob("*.json"))
        with mock.patch.object(shopping, "has_api_key", return_value=True), mock.patch.object(
            shopping, "fetch_shopping", side_effect=shopping.SerpApiError("down")
        ):
            result = analyze_query(cache_dir=self.tmp, query="iPhone 15 128GB")
        self.assertEqual(result.get("error"), "api_error")
        self.assertEqual(sorted(p.name for p in self.tmp.glob("*.json")), before)
        # The unrelated valid cache is still readable.
        self.assertIsNotNone(shopping.load_cached_for_query(self.tmp, "Sony WH-1000XM4"))


class AvailabilityLensTests(unittest.TestCase):
    """First-seen vs broader-eligible comparison must stay strictly data-driven."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            p.unlink()
        self.tmp.rmdir()

    def _mac(self, rank, price, source=None):
        return item(
            "Apple MacBook Air M1 8GB 256GB", price,
            position=rank, source=source or ("shop%s" % rank),
        )

    def test_eligible_price_calculations_for_each_group(self):
        listings = [
            self._mac(1, 1000), self._mac(2, 2000),
            self._mac(3, 3000), self._mac(12, 4000),
        ]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        # First-seen keeps only ranks <= 10.
        self.assertEqual(a["first_seen"]["prices"], [1000, 2000, 3000])
        self.assertEqual(a["broader"]["prices"], [1000, 2000, 3000, 4000])
        f = a["first_seen"]["statistics"]
        self.assertEqual((f["minimum"], f["q1"], f["median"], f["q3"], f["maximum"]),
                         (1000, 1000, 2000, 2000, 3000))
        b = a["broader"]["statistics"]
        self.assertEqual((b["minimum"], b["q1"], b["median"], b["q3"], b["maximum"], b["spread"]),
                         (1000, 1000, 2500, 3000, 4000, 3000))
        self.assertTrue(a["comparable"])
        self.assertEqual(a["difference"]["median_delta"], -500)
        self.assertEqual(a["difference"]["direction"], "lower")

    def test_first_seen_uses_rank_not_list_order(self):
        listings = [
            self._mac(12, 4000), self._mac(1, 1000),
            self._mac(2, 2000), self._mac(3, 3000),
        ]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        self.assertEqual(a["first_seen"]["prices"], [1000, 2000, 3000])
        self.assertEqual(a["first_seen"]["rank_min"], 1)
        self.assertEqual(a["first_seen"]["rank_max"], 3)

    def test_missing_rank_falls_back_to_response_order(self):
        listings = [
            item("Apple MacBook Air M1 8GB 256GB", 1000, source="a"),
            item("Apple MacBook Air M1 8GB 256GB", 2000, source="b"),
            item("Apple MacBook Air M1 8GB 256GB", 3000, source="c"),
        ]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        self.assertEqual(a["first_seen"]["rank_min"], 1)
        self.assertEqual(a["first_seen"]["rank_max"], 3)
        self.assertEqual(a["first_seen"]["prices"], a["broader"]["prices"])

    def test_groups_overlap_and_first_is_subset(self):
        listings = [self._mac(r, r * 1000) for r in (1, 2, 3, 20, 30)]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        self.assertTrue(a["first_is_subset_of_broader"])
        self.assertEqual(a["overlap_count"], a["first_seen"]["listing_count"])
        self.assertTrue(set(a["first_seen"]["prices"]).issubset(set(a["broader"]["prices"])))

    def test_insufficient_when_first_page_empty(self):
        listings = [self._mac(r, r * 1000) for r in (11, 12, 13, 14)]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        self.assertEqual(a["first_seen"]["listing_count"], 0)
        self.assertTrue(a["broader"]["sufficient"])
        self.assertFalse(a["comparable"])
        self.assertIsNone(a["difference"])

    def test_insufficient_when_overall_evidence_too_small(self):
        listings = [self._mac(1, 1000), self._mac(2, 2000)]
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", listings)
        a = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        self.assertFalse(a["comparable"])

    def test_accessories_and_mismatches_excluded_from_lens(self):
        listings = [
            item("Samsung Galaxy A17 5G (Black, 6GB-128GB)", 20000, position=1, source="s1"),
            item("Samsung Galaxy A17 5G (Blue, 6GB-128GB)", 21000, position=2, source="s2"),
            item("Samsung Galaxy A17 5G (White, 6GB-128GB)", 22000, position=3, source="s3"),
            item("Samsung Galaxy A17 5G Back Cover", 99, position=4, source="s4"),
            item("Samsung Galaxy M17 5G", 18000, position=5, source="s5"),
            item("Samsung Galaxy A17 5G LCD Screen Display", 4999, position=6, source="s6"),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        result = estimate_price(self.tmp, query="samsung A17")
        a = result["availability"]
        self.assertEqual(a["broader"]["prices"], [20000, 21000, 22000])
        self.assertEqual(a["first_seen"]["prices"], [20000, 21000, 22000])
        self.assertEqual(result["summary"]["accessories"], 2)
        self.assertEqual(result["summary"]["mismatches"], 1)

    def test_missing_price_is_counted_but_never_invented(self):
        listings = [
            item("Samsung Galaxy A17 5G Alpha", 20000, position=1, source="a"),
            item("Samsung Galaxy A17 5G Beta", 21000, position=2, source="b"),
            item("Samsung Galaxy A17 5G Gamma", 22000, position=3, source="c"),
            item("Samsung Galaxy A17 5G Delta", None, position=4, source="d"),
        ]
        write_cache(self.tmp, "samsung A17", listings)
        a = estimate_price(self.tmp, query="samsung A17")["availability"]
        self.assertEqual(a["broader"]["listing_count"], 4)
        self.assertEqual(a["broader"]["priced_count"], 3)
        self.assertNotIn(None, a["broader"]["prices"])
        self.assertEqual(sum(1 for p in a["broader"]["prices"] if p is None), 0)

    def test_different_product_queries_produce_different_lenses(self):
        write_cache(self.tmp, "MacBook Air M1 8GB 256GB", [self._mac(r, r * 1000) for r in (1, 2, 3)])
        write_cache(self.tmp, "iPhone 13 128GB", [
            item("Apple iPhone 13 128GB", 30000, position=1, source="i1"),
            item("Apple iPhone 13 128GB", 40000, position=2, source="i2"),
            item("Apple iPhone 13 128GB", 50000, position=3, source="i3"),
        ])
        mac = estimate_price(self.tmp, query="MacBook Air M1 8GB 256GB")["availability"]
        iph = estimate_price(self.tmp, query="iPhone 13 128GB")["availability"]
        self.assertEqual(mac["broader"]["statistics"]["median"], 2000)
        self.assertEqual(iph["broader"]["statistics"]["median"], 40000)
        self.assertTrue(mac["comparable"] and iph["comparable"])


if __name__ == "__main__":
    unittest.main()
