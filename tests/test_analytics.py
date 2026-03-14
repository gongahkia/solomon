import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analytics import grade_counts_from_history, review_activity, stats_pages
from schema import new_card


class AnalyticsTests(unittest.TestCase):
    def test_grade_counts_from_history_aggregates_grades(self):
        events = [
            {"grade": 0},
            {"grade": 2},
            {"grade": 2},
            {"grade": 3},
        ]
        counts = grade_counts_from_history(events)
        self.assertEqual(counts["again"], 1)
        self.assertEqual(counts["good"], 2)
        self.assertEqual(counts["easy"], 1)

    def test_stats_pages_include_review_activity_page(self):
        card = new_card("Q", "A")
        valid_statuses = [{"filename": "deck.sko", "valid": True, "sets": {"set_a": [card]}}]
        events = [
            {
                "timestamp": "2026-03-14T10:00:00",
                "grade": 2,
                "deck_name": "deck.sko",
                "set_name": "set_a",
            }
        ]
        pages = stats_pages(valid_statuses, events, {"srs": {"leech_threshold": 8}})
        titles = [title for title, _ in pages]
        self.assertIn("Review Activity", titles)
        self.assertIn("Overview", titles)


if __name__ == "__main__":
    unittest.main()
