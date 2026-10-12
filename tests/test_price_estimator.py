import json
import os
import unittest
from pathlib import Path

# Import the modules under test
from backend.price_estimator import estimate_price, _statistics
from backend.shopping import classify_item

class TestPriceEstimator(unittest.TestCase):
    def setUp(self):
        # Create a temporary cache directory inside the test directory
        self.test_dir = Path(__file__).parent / "tmp_test_cache"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        # Build a synthetic cached JSON payload
        self.payload = {
            "response": {
                "shopping_results": [
                    # Exact spec confirmed
                    {
                        "title": "Apple MacBook Air with M1 Chip 8GB RAM 256GB SSD",
                        "extracted_price": 90000,
                        "source": "example.com",
                        "product_link": "http://example.com/item1",
                        "second_hand_condition": "pre-owned",
                        "multiple_sources": False,
                    },
                    # Ambiguous (missing RAM)
                    {
                        "title": "Apple MacBook Air with M1 Chip 256GB SSD",
                        "extracted_price": 85000,
                        "source": "example.com",
                        "product_link": "http://example.com/item2",
                        "second_hand_condition": "pre-owned",
                        "multiple_sources": False,
                    },
                    # Mismatch (Intel)
                    {
                        "title": "Apple MacBook Air with Intel i5 8GB 256GB",
                        "extracted_price": 80000,
                        "source": "example.com",
                        "product_link": "http://example.com/item3",
                        "second_hand_condition": "pre-owned",
                        "multiple_sources": False,
                    },
                    # Multiple sources ambiguous but promoted
                    {
                        "title": "Apple MacBook Air with M2 Chip 8GB 256GB SSD",
                        "extracted_price": 95000,
                        "source": "example.com",
                        "product_link": "http://example.com/item4",
                        "second_hand_condition": "pre-owned",
                        "multiple_sources": True,
                    },
                ]
            }
        }
        # Write to cache file with timestamped name matching pattern
        cache_file = self.test_dir / "google_shopping_MacBook_Air_M1_8GB_256GB_used_20261012T000000Z.json"
        cache_file.write_text(json.dumps(self.payload), encoding="utf-8")
        self.cache_dir = self.test_dir

    def tearDown(self):
        # Remove temporary files
        for child in self.test_dir.rglob("*"):
            child.unlink()
        self.test_dir.rmdir()

    def test_classification(self):
        # The first item should be confirmed
        self.assertEqual(classify_item(self.payload['response']['shopping_results'][0]), "confirmed")
        # The second item is ambiguous (missing RAM spec)
        self.assertEqual(classify_item(self.payload['response']['shopping_results'][1]), "ambiguous")
        # The third item is a mismatch (Intel)
        self.assertEqual(classify_item(self.payload['response']['shopping_results'][2]), "mismatch")
        # The fourth item lacks M1 but has multiple_sources; it is still an
        # ambiguous (non-)match and must not be promoted to a verified match.
        self.assertEqual(classify_item(self.payload['response']['shopping_results'][3]), "ambiguous")

    def test_estimate_price_counts_and_confidence(self):
        # Run estimator on the synthetic cache
        result = estimate_price(cache_dir=self.cache_dir)
        # Since only one confirmed price, we expect insufficient evidence status
        self.assertEqual(result["status"], "insufficient_evidence")
        summary = result["summary"]
        self.assertEqual(summary["eligible_price_count"], 1)
        # Available prices should contain the single confirmed price
        self.assertEqual(result["available_prices"], [90000])
        # Verify aggregated listings are reported separately
        evidence = result["evidence"]
        self.assertIn("aggregated", evidence)
        # A multi-source listing that does not actually match the query is NOT a
        # verified match: it must stay in its true (ambiguous) section so the
        # aggregated group never overstates certainty.
        self.assertEqual(len(evidence["aggregated"]), 0)
        self.assertTrue(any("M2 Chip" in it["title"] for it in evidence["ambiguous"]))
        self.assertFalse(any("M2 Chip" in it["title"] for it in evidence["aggregated"]))

    def test_statistics_low_confidence_for_small_samples(self):
        # Directly test _statistics helper for a 3‑item list
        prices = [100, 200, 300]
        stats = _statistics(prices)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["confidence"], "low")

if __name__ == "__main__":
    unittest.main()
