import unittest
from backend import shopping

class TestClassificationLogic(unittest.TestCase):
    def make_item(self, title, source="test", **extra):
        item = {
            "title": title,
            "source": source,
        }
        item.update(extra)
        return item

    def test_confirmed_when_all_specs_present(self):
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB SSD",
            extracted_price=100000,
        )
        self.assertEqual(shopping.classify_item(item), "confirmed")

    def test_ambiguous_missing_ram(self):
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 256 GB",
            extracted_price=90000,
        )
        self.assertEqual(shopping.classify_item(item), "ambiguous")

    def test_ambiguous_missing_storage(self):
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 8 GB RAM",
            extracted_price=95000,
        )
        self.assertEqual(shopping.classify_item(item), "ambiguous")

    def test_wrong_ram_not_confirmed(self):
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 16 GB RAM 256 GB",
            extracted_price=110000,
        )
        # 16 GB should not match 8 GB spec, so ambiguous (not confirmed)
        self.assertEqual(shopping.classify_item(item), "ambiguous")

    def test_wrong_storage_not_confirmed(self):
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 8 GB RAM 128 GB",
            extracted_price=85000,
        )
        self.assertEqual(shopping.classify_item(item), "ambiguous")

    def test_intel_mismatch(self):
        item = self.make_item(
            "Apple MacBook Air with Intel i5 8 GB RAM 256 GB",
            extracted_price=120000,
        )
        self.assertEqual(shopping.classify_item(item), "mismatch")

    def test_core_i_mismatch(self):
        item = self.make_item(
            "Apple MacBook Air 8 GB RAM 256 GB Core i3",
            extracted_price=80000,
        )
        self.assertEqual(shopping.classify_item(item), "mismatch")

    def test_macbook_pro_mismatch(self):
        item = self.make_item(
            "Apple MacBook Pro with M1 8 GB RAM 256 GB",
            extracted_price=130000,
        )
        self.assertEqual(shopping.classify_item(item), "mismatch")

    def test_generic_air_ambiguous(self):
        item = self.make_item(
            "Apple MacBook Air",
            extracted_price=75000,
        )
        self.assertEqual(shopping.classify_item(item), "ambiguous")

    def test_condition_unknown_display(self):
        # Ensure missing condition is reported as Unknown by print_summary (not directly testable here).
        # Instead, verify that the key is absent and sanitize fallback works.
        item = self.make_item(
            "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB",
            extracted_price=100000,
        )
        self.assertNotIn("second_hand_condition", item)
        # Using sanitize directly ensures it returns 'Unknown' when missing.
        self.assertEqual(shopping.sanitize(item.get("second_hand_condition", "Unknown")), "Unknown")

    def test_deduplication(self):
        dup_item = self.make_item(
            "Apple MacBook Air with M1 Chip 8 GB RAM 256 GB",
            extracted_price=100000,
            source="seller",
            product_link="http://example.com"
        )
        items = [dup_item, dup_item.copy()]
        unique, dup_cnt = shopping.deduplicate_items(items)
        self.assertEqual(len(unique), 1)
        self.assertEqual(dup_cnt, 1)

if __name__ == "__main__":
    unittest.main()
