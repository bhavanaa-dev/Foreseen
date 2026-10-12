import unittest
from pathlib import Path

# Import the module under test
from backend import shopping

class TestShoppingOffline(unittest.TestCase):
    def setUp(self):
        # Project root is two levels up from this test file (tests/ -> project root)
        self.project_root = Path(__file__).resolve().parent.parent
        self.cache_dir = self.project_root / "cache"
        self.query = "MacBook Air M1 8GB 256GB used"
        # Load cached response (no network)
        self.response = shopping.load_cached_response(self.cache_dir, self.query)
        self.results = self.response.get("shopping_results", [])

    def test_load_cached_response(self):
        # Ensure we have some results
        self.assertGreater(len(self.results), 0, "Cached response should contain shopping results")

    def test_deduplication(self):
        unique, dup_cnt = shopping.deduplicate_items(self.results)
        # Duplicates should be non‑negative and less than total
        self.assertGreaterEqual(dup_cnt, 0)
        self.assertLessEqual(len(unique), len(self.results))

    def test_classification_counts(self):
        unique, _ = shopping.deduplicate_items(self.results)
        counts = {"confirmed": 0, "ambiguous": 0, "mismatch": 0}
        for item in unique:
            cls = shopping.classify_item(item)
            self.assertIn(cls, counts)
            counts[cls] += 1
        # Ensure at least one confirmed or ambiguous entry exists for the target product
        self.assertTrue(counts["confirmed"] > 0 or counts["ambiguous"] > 0,
                        "There should be at least one listing that matches or could match the target spec")

if __name__ == "__main__":
    unittest.main()
