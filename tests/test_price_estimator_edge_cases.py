import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.price_estimator import estimate_price


class TestPriceEstimatorEdgeCases(unittest.TestCase):
    def _write_cache(self, listings):
        """Helper to write a temporary cache JSON file with given listings."""
        cache_dir = Path(tempfile.mkdtemp())
        payload = {
            "response": {
                "shopping_results": listings
            }
        }
        cache_file = cache_dir / "google_shopping_test_used.json"
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
        return cache_dir

    def test_zero_eligible_prices(self):
        # All listings missing extracted_price and price fields -> no eligible prices.
        listings = [
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerA", "product_link": "http://example.com/1"},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerB", "product_link": "http://example.com/2"},
        ]
        cache_dir = self._write_cache(listings)
        result = estimate_price(cache_dir=cache_dir)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 0)
        self.assertEqual(result["available_prices"], [])

    def test_one_eligible_price(self):
        # One confirmed listing with price, others missing price.
        listings = [
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerA", "product_link": "http://example.com/1", "extracted_price": 55000, "price": "₹55,000"},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerB", "product_link": "http://example.com/2"},
        ]
        cache_dir = self._write_cache(listings)
        result = estimate_price(cache_dir=cache_dir)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 1)
        self.assertEqual(result["available_prices"], [55000])

    def test_two_eligible_prices(self):
        # Two confirmed listings with valid prices -> still insufficient evidence.
        listings = [
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerA", "product_link": "http://example.com/1", "extracted_price": 55000},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerB", "product_link": "http://example.com/2", "extracted_price": 57000},
        ]
        cache_dir = self._write_cache(listings)
        result = estimate_price(cache_dir=cache_dir)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 2)
        self.assertCountEqual(result["available_prices"], [55000, 57000])

    def test_three_eligible_prices_preliminary(self):
        # Three confirmed listings with valid prices -> preliminary estimate.
        listings = [
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerA", "product_link": "http://example.com/1", "extracted_price": 55000},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerB", "product_link": "http://example.com/2", "extracted_price": 57000},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerC", "product_link": "http://example.com/3", "extracted_price": 59000},
        ]
        cache_dir = self._write_cache(listings)
        result = estimate_price(cache_dir=cache_dir)
        self.assertEqual(result["status"], "preliminary")
        self.assertEqual(result["summary"]["eligible_price_count"], 3)
        stats = result.get("statistics", {})
        self.assertIn("count", stats)
        self.assertEqual(stats["count"], 3)
        # Confidence must be low per implementation.
        self.assertEqual(stats.get("confidence"), "low")

    def test_aggregated_listings_not_counted(self):
        # Two aggregated listings (multiple_sources=True) and one confirmed price.
        listings = [
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": True, "seller": "SellerAgg1", "product_link": "http://example.com/agg1", "extracted_price": 56000},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": True, "seller": "SellerAgg2", "product_link": "http://example.com/agg2", "extracted_price": 57000},
            {"title": "Apple MacBook Air M1 8GB 256GB", "multiple_sources": False, "seller": "SellerA", "product_link": "http://example.com/1", "extracted_price": 55000},
        ]
        cache_dir = self._write_cache(listings)
        result = estimate_price(cache_dir=cache_dir)
        # Only one eligible price -> insufficient evidence.
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"]["eligible_price_count"], 1)
        # Aggregated count should be recorded.
        self.assertEqual(result["summary"]["aggregated"], 2)
        self.assertIn("aggregated", result["evidence"])
        self.assertEqual(len(result["evidence"]["aggregated"]), 2)

if __name__ == "__main__":
    unittest.main()
