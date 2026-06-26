import unittest

from sporepath.app import (
    DEBUG_ACTION_LABELS,
    INSPIRE_RATING_OPTIONS,
    PRIMARY_ACTION_LABELS,
    SERVICE_STATUS_LABELS,
    build_service_statuses,
    feedback_status_from_rating,
    feedback_statuses_for_suggestions,
    service_status_text,
    should_show_feedback_controls,
    status_light_color,
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

    def test_service_status_labels_cover_background_services(self):
        self.assertEqual(SERVICE_STATUS_LABELS, ("ArcRift", "Sources", "Queue"))

    def test_service_statuses_use_launcher_pids_and_arcrift_check(self):
        statuses = build_service_statuses(
            env={
                "SPOREPATH_SOURCES_WATCHER_PID": "12",
                "SPOREPATH_QUEUE_WORKER_PID": "34",
            },
            pid_checker=lambda pid: pid == 12,
            arcrift_checker=lambda: True,
        )

        self.assertEqual(statuses["arcrift"].state, "ok")
        self.assertEqual(statuses["sources"].state, "ok")
        self.assertEqual(statuses["queue"].state, "down")
        self.assertEqual(service_status_text(statuses["sources"]), "Sources: on")
        self.assertEqual(service_status_text(statuses["queue"]), "Queue: down")
        self.assertEqual(status_light_color("ok"), "#1a7f37")

    def test_service_statuses_mark_missing_worker_pids_as_off(self):
        statuses = build_service_statuses(
            env={},
            pid_checker=lambda _pid: True,
            arcrift_checker=lambda: False,
        )

        self.assertEqual(statuses["arcrift"].state, "down")
        self.assertEqual(statuses["sources"].state, "off")
        self.assertEqual(statuses["queue"].state, "off")


if __name__ == "__main__":
    unittest.main()
