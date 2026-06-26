import unittest

from sporepath.app import (
    DEBUG_ACTION_LABELS,
    INSPIRE_RATING_OPTIONS,
    PRIMARY_ACTION_LABELS,
    feedback_status_from_rating,
    feedback_statuses_for_suggestions,
    should_show_feedback_controls,
)


class AppUiLayoutTests(unittest.TestCase):
    def test_primary_actions_keep_daily_surface_small(self):
        self.assertEqual(PRIMARY_ACTION_LABELS, ("Sync Vault", "Debug", "Inspire"))
        self.assertNotIn("Mark Useful", PRIMARY_ACTION_LABELS)

    def test_debug_actions_hold_manual_maintenance_buttons(self):
        self.assertEqual(
            DEBUG_ACTION_LABELS,
            (
                "Auto-detect Sources",
                "Import ArcRift",
                "Refresh Now",
                "Open Vault",
                "Queue Status",
                "Run Queue Batch",
            ),
        )

    def test_feedback_controls_only_show_after_inspire_suggestions_exist(self):
        self.assertFalse(should_show_feedback_controls(None, 0))
        self.assertFalse(should_show_feedback_controls("run-1", 0))
        self.assertTrue(should_show_feedback_controls("run-1", 1))

    def test_feedback_ratings_are_structured_and_note_free(self):
        self.assertEqual(INSPIRE_RATING_OPTIONS, (("up", "👍", "useful"), ("down", "👎", "wrong")))
        self.assertEqual(feedback_status_from_rating("up"), "useful")
        self.assertEqual(feedback_status_from_rating("down"), "wrong")
        self.assertEqual(feedback_status_from_rating(""), "ignored")
        with self.assertRaises(ValueError):
            feedback_status_from_rating("maybe")

    def test_unselected_suggestions_are_submitted_as_ignored(self):
        statuses = feedback_statuses_for_suggestions(
            ["1", "2", "3"],
            {"1": "up", "2": "down"},
        )

        self.assertEqual(statuses, {"1": "useful", "2": "wrong", "3": "ignored"})


if __name__ == "__main__":
    unittest.main()
