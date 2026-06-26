import unittest

from sporepath.app import DEBUG_ACTION_LABELS, PRIMARY_ACTION_LABELS, should_show_feedback_controls


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


if __name__ == "__main__":
    unittest.main()
