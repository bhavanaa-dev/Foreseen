import sys
import pathlib
import unittest
from unittest import mock

# Add the backend directory to sys.path to import the Flask app
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
import app as app_backend

app = app_backend.app


class AnalyzeRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_home_get(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'FORESEEN', resp.data)

    def test_analyze_post_success(self):
        # Use a query that matches the target specs
        resp = self.client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
        self.assertEqual(resp.status_code, 200)
        # Should contain Result status in the rendered page
        self.assertIn(b'Result:', resp.data)

    def test_analyze_get(self):
        # GET should return the home page (200)
        resp = self.client.get('/analyze')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'FORESEEN', resp.data)


class EvidenceRenderingTest(unittest.TestCase):
    """An honest 'not enough evidence' result must still show the evidence."""

    def setUp(self):
        self.client = app.test_client()

    def _fake_result(self):
        return {
            "status": "insufficient_evidence",
            "available_prices": [22000.0],
            "summary": {
                "eligible_price_count": 1,
                "confirmed": 0,
                "ambiguous": 0,
                "mismatches": 8,
                "accessories": 23,
                "aggregated": 9,
            },
            "evidence": {
                "confirmed": [],
                "ambiguous": [],
                "mismatches": [],
                "accessories": [
                    {
                        "title": "Samsung Galaxy A17 5G Back Cover",
                        "price": 149,
                        "source": "shop",
                        "url": "http://x",
                        "condition": "Unknown",
                        "multiple_sources": False,
                    }
                ],
                "aggregated": [
                    {
                        "title": "Samsung Galaxy A17 5G (Black, 6GB-128GB)",
                        "price": 22000,
                        "source": None,
                        "url": "http://y",
                        "condition": "Unknown",
                        "multiple_sources": True,
                    }
                ],
            },
            "origin": "cache",
        }

    def test_insufficient_with_evidence_is_not_a_dead_end(self):
        with mock.patch.object(app_backend, "analyze_query", return_value=self._fake_result()):
            resp = self.client.post('/analyze', data={'query': 'samsung A17'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        # Not the dead-end page.
        self.assertNotIn('Not enough matching evidence', html)
        # Evidence and its reasons stay visible.
        self.assertIn('Evidence we examined', html)
        self.assertIn('Accessories &amp; parts', html)
        self.assertIn('Verified matches across sources', html)
        # The genuine match is shown.
        self.assertIn('Samsung Galaxy A17 5G (Black, 6GB-128GB)', html)

    def test_empty_result_still_renders_without_evidence(self):
        empty = {
            "status": "insufficient_evidence",
            "available_prices": [],
            "summary": {"eligible_price_count": 0},
            "evidence": {"confirmed": [], "ambiguous": [], "mismatches": [],
                          "accessories": [], "aggregated": []},
            "origin": "cache",
        }
        with mock.patch.object(app_backend, "analyze_query", return_value=empty):
            resp = self.client.post('/analyze', data={'query': 'nothing at all'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Not enough matching evidence', html)

    def test_exclusion_reason_is_shown_for_rejected_listings(self):
        result = self._fake_result()
        result["evidence"]["accessories"][0]["classification"] = "accessory"
        result["evidence"]["accessories"][0]["exclusion"] = "case or cover"
        with mock.patch.object(app_backend, "analyze_query", return_value=result):
            resp = self.client.post('/analyze', data={'query': 'samsung A17'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Why it&rsquo;s excluded:', html)
        self.assertIn('case or cover', html)


class AvailabilityLensRenderingTest(unittest.TestCase):
    """The Availability Lens must render from result data, with limitations."""

    def setUp(self):
        self.client = app.test_client()

    def _stats(self, prices):
        return {
            "count": len(prices), "minimum": prices[0], "maximum": prices[-1],
            "median": prices[len(prices) // 2], "q1": prices[0],
            "q3": prices[len(prices) // 2], "spread": prices[-1] - prices[0],
            "confidence": "low",
        }

    def _result(self, first_prices, broader_prices, difference):
        return {
            "status": "preliminary",
            "statistics": self._stats(broader_prices),
            "summary": {"eligible_price_count": len(broader_prices)},
            "evidence": {"confirmed": [], "ambiguous": [], "mismatches": [],
                          "accessories": [], "aggregated": []},
            "origin": "cache",
            "availability": {
                "first_page_size": 10,
                "first_seen": {
                    "listing_count": len(first_prices), "priced_count": len(first_prices),
                    "prices": first_prices, "statistics": self._stats(first_prices) if first_prices else {},
                    "sufficient": len(first_prices) >= 3, "rank_min": 1,
                    "rank_max": len(first_prices) or None,
                },
                "broader": {
                    "listing_count": len(broader_prices), "priced_count": len(broader_prices),
                    "prices": broader_prices, "statistics": self._stats(broader_prices),
                    "sufficient": len(broader_prices) >= 3, "rank_min": 1,
                    "rank_max": len(broader_prices),
                },
                "comparable": bool(difference),
                "overlap_count": len(first_prices),
                "first_is_subset_of_broader": True,
                "difference": difference,
            },
        }

    def test_lens_renders_when_comparable(self):
        result = self._result(
            [100, 200, 300], [100, 200, 300, 400],
            {"median_delta": -50, "abs_median_delta": 50, "percent": -20.0, "direction": "lower"},
        )
        with mock.patch.object(app_backend, "analyze_query", return_value=result):
            resp = self.client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Availability Lens', html)
        self.assertIn('Seen first', html)
        self.assertIn('All eligible listings', html)
        self.assertIn('lower', html)
        # Limitations note must always be present.
        self.assertIn('not the entire market', html)
        self.assertIn('What this means', html)
        self.assertIn('How is this calculated?', html)

    def test_lens_explains_no_first_page_price(self):
        result = self._result(
            [], [100, 200, 300, 400], None,
        )
        with mock.patch.object(app_backend, "analyze_query", return_value=result):
            resp = self.client.post('/analyze', data={'query': 'samsung A17'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Availability Lens', html)
        self.assertIn('no first-page price to compare', html)

    def test_lens_shows_single_observation_as_a_point(self):
        result = self._result([150000], [150000], None)
        with mock.patch.object(app_backend, "analyze_query", return_value=result):
            resp = self.client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('only listing', html)
        self.assertIn('one observation rather than a market price', html)
        self.assertIn('scale-dot', html)


class AvailabilityLensViewTest(unittest.TestCase):
    """Edge-case coverage for the lens view model (no HTTP layer)."""

    def _avail(self, prices, first=None):
        first = list(prices if first is None else first)

        def stats(vals):
            if not vals:
                return {}
            ordered = sorted(vals)
            n = len(ordered)
            return {
                "count": n, "minimum": ordered[0], "maximum": ordered[-1],
                "median": ordered[n // 2],
                "q1": ordered[max(0, round(0.25 * n + 0.5) - 1)],
                "q3": ordered[min(n - 1, round(0.75 * n + 0.5) - 1)],
                "spread": ordered[-1] - ordered[0], "confidence": "low",
            }

        prices = list(prices)
        return {
            "first_page_size": 10,
            "first_seen": {
                "listing_count": len(first), "priced_count": len(first),
                "prices": first, "statistics": stats(first),
                "sufficient": len(first) >= 3, "rank_min": 1,
                "rank_max": len(first) or None,
            },
            "broader": {
                "listing_count": len(prices), "priced_count": len(prices),
                "prices": prices, "statistics": stats(prices),
                "sufficient": len(prices) >= 3, "rank_min": 1,
                "rank_max": len(prices),
            },
            "comparable": False, "overlap_count": len(first),
            "first_is_subset_of_broader": True, "difference": None,
        }

    def test_empty_evidence(self):
        view = app_backend._build_availability_view(self._avail([], first=[]))
        self.assertFalse(view["show"])
        self.assertFalse(view["has_prices"])
        self.assertIn("nothing to chart", " ".join(view["insights"]))

    def test_single_listing(self):
        view = app_backend._build_availability_view(self._avail([500], first=[500]))
        self.assertTrue(view["show"])
        self.assertTrue(view["single"])
        self.assertEqual(view["median_label"], "only listing")
        self.assertEqual(view["median_pos"], 50.0)
        self.assertEqual(len(view["dots"]), 1)

    def test_three_listings_wide_range(self):
        view = app_backend._build_availability_view(self._avail([100, 500, 900]))
        self.assertEqual(view["count"], 3)
        self.assertEqual((view["min_pos"], view["max_pos"]), (0.0, 100.0))
        self.assertFalse(view["has_quartiles"])
        self.assertIn("vary considerably", view["range_explanation"])

    def test_repeated_prices_share_markers(self):
        view = app_backend._build_availability_view(self._avail([200, 200, 300, 300, 300]))
        counts = {d["label"]: d["count"] for d in view["dots"]}
        self.assertEqual(len(view["dots"]), 2)
        self.assertEqual(counts[app_backend.format_inr(300)], 3)

    def test_large_outlier_offers_zoom_without_hiding_range(self):
        view = app_backend._build_availability_view(self._avail([100, 110, 120, 130, 5000]))
        self.assertIsNotNone(view["compact"])
        self.assertEqual(view["compact"]["excluded"], 1)
        self.assertEqual(view["compact"]["outside_max"], app_backend.format_inr(5000))
        self.assertEqual((view["min_pos"], view["max_pos"]), (0.0, 100.0))


if __name__ == '__main__':
    unittest.main()
