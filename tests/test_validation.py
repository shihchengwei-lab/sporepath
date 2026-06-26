import json
import tempfile
import unittest
from pathlib import Path

from sporepath.models import DigestedNote, ThoughtAtom
from sporepath.store import MemoryStore
from sporepath.validation import (
    validate_inspire,
    validate_notes,
    validate_report,
    validate_scout,
)


def atom(atom_id: str, *, activation: float = 0.3) -> ThoughtAtom:
    return ThoughtAtom(
        id=atom_id,
        source=f"chat.jsonl:line[{atom_id}]",
        role="user",
        text=f"{atom_id} reusable memory",
        summary=f"{atom_id} summary",
        kind="idea",
        tags=["memory"],
        timestamp=None,
        importance=0.7,
        activation=activation,
        metadata={},
    )


class ValidationTests(unittest.TestCase):
    def test_validate_scout_scores_eval_sheet_with_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            rows = [
                {
                    "id": f"good-{index}",
                    "text": f"A useful memory {index}",
                    "prediction": {
                        "keep": True,
                        "route": "debug",
                        "handoff": "Use this for debugging.",
                        "tags": ["debug"],
                    },
                    "human": {
                        "keep": True,
                        "route": "debug",
                        "signal_found": True,
                        "noise_marked": True,
                        "handoff_sufficient": True,
                        "useful": True,
                    },
                }
                for index in range(29)
            ]
            rows.append(
                {
                    "id": "parse-error",
                    "text": "Important but failed",
                    "prediction": {
                        "keep": False,
                        "route": "other",
                        "handoff": "",
                        "tags": ["extractor-error"],
                    },
                    "human": {
                        "keep": True,
                        "route": "decision",
                        "signal_found": False,
                        "noise_marked": False,
                        "handoff_sufficient": False,
                        "useful": False,
                    },
                }
            )
            sheet.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            result = validate_scout(sheet)

        self.assertEqual(result.metrics["total_cases"], 30)
        self.assertEqual(result.metrics["parse_error_count"], 1)
        self.assertEqual(result.metrics["false_negative_count"], 1)
        self.assertEqual(result.metrics["false_positive_count"], 0)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("Scout Validator", result.markdown)

    def test_validate_scout_fails_when_model_keeps_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            rows = []
            for index in range(24):
                rows.append(
                    {
                        "id": f"good-{index}",
                        "text": f"Useful memory {index}",
                        "prediction": {"keep": True, "route": "idea", "tags": [], "handoff": "Use later."},
                        "human": {
                            "keep": True,
                            "route": "idea",
                            "signal_found": True,
                            "noise_marked": True,
                            "handoff_sufficient": True,
                            "useful": True,
                        },
                    }
                )
            for index in range(6):
                rows.append(
                    {
                        "id": f"noise-{index}",
                        "text": f"Disposable status recap {index}",
                        "prediction": {"keep": True, "route": "ops", "tags": [], "handoff": "Use later."},
                        "human": {
                            "keep": False,
                            "route": "other",
                            "signal_found": False,
                            "noise_marked": False,
                            "handoff_sufficient": False,
                            "useful": False,
                        },
                    }
                )
            sheet.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            result = validate_scout(sheet)

        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.metrics["false_positive_count"], 6)
        self.assertAlmostEqual(result.metrics["false_positive_rate"], 0.2)

    def test_validate_scout_needs_enough_scored_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            rows = [
                {
                    "id": f"case-{index}",
                    "text": f"Useful unique memory fragment {index}",
                    "prediction": {"keep": True, "route": "idea", "tags": [], "handoff": "Use later."},
                    "human": {
                        "keep": True,
                        "route": "idea",
                        "signal_found": True,
                        "noise_marked": True,
                        "handoff_sufficient": True,
                        "useful": True,
                    },
                }
                for index in range(5)
            ]
            sheet.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            result = validate_scout(sheet)

        self.assertEqual(result.verdict, "needs_data")
        self.assertEqual(result.metrics["minimum_scored_cases"], 30)

    def test_validate_notes_checks_sources_and_empty_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms([atom("a1"), atom("a2")])
            store.upsert_notes(
                [
                    DigestedNote(
                        id="good-note",
                        title="Concept note: memory",
                        note_type="concept_note",
                        summary="Useful note",
                        key_points=["Useful point"],
                        open_questions=[],
                        tags=["memory"],
                        source_atom_ids=["a1", "a2"],
                        source_spans=["chat.jsonl:line[a1]", "chat.jsonl:line[a2]"],
                        activation=0.5,
                        metadata={},
                    ),
                    DigestedNote(
                        id="bad-note",
                        title="Empty note",
                        note_type="concept_note",
                        summary="",
                        key_points=[],
                        open_questions=[],
                        tags=[],
                        source_atom_ids=[],
                        source_spans=[],
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )

            result = validate_notes(store)

        self.assertEqual(result.metrics["notes_count"], 2)
        self.assertEqual(result.metrics["empty_note_count"], 1)
        self.assertEqual(result.metrics["notes_with_sources"], 1)
        self.assertEqual(result.verdict, "fail")

    def test_validate_inspire_reports_feedback_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms([atom("focus", activation=0.8), atom("latent", activation=0.1)])
            run_id = store.record_inspire_run(
                question="How do I validate this?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="suggestion_id: 1",
            )
            store.record_inspire_suggestions(
                run_id,
                [
                    {
                        "suggestion_id": "1",
                        "text": "Use the latent bridge.",
                        "cited_atom_ids": ["focus", "latent"],
                    }
                ],
            )
            store.apply_inspire_feedback(
                run_id,
                suggestion_id="1",
                status="useful",
                note="This suggestion changed the next experiment.",
            )

            result = validate_inspire(store)

        self.assertEqual(result.metrics["runs_count"], 1)
        self.assertEqual(result.metrics["suggestions_count"], 1)
        self.assertEqual(result.metrics["positive_feedback_count"], 1)
        self.assertEqual(result.metrics["inspire_run_event_count"], 1)
        self.assertEqual(result.metrics["inspire_feedback_event_count"], 1)
        self.assertEqual(result.verdict, "pass")

    def test_validate_inspire_accepts_structured_feedback_without_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms([atom("focus", activation=0.8), atom("latent", activation=0.1)])
            run_id = store.record_inspire_run(
                question="How do I validate this?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="suggestion_id: 1",
            )
            store.record_inspire_suggestions(
                run_id,
                [
                    {
                        "suggestion_id": "1",
                        "text": "Use the latent bridge.",
                        "cited_atom_ids": ["focus", "latent"],
                    }
                ],
            )
            store.apply_inspire_feedback(run_id, suggestion_id="1", status="useful")
            store.apply_inspire_feedback(run_id, suggestion_id="1", status="wrong")
            store.apply_inspire_feedback(run_id, suggestion_id="1", status="ignored")

            result = validate_inspire(store)

        self.assertEqual(result.metrics["positive_feedback_count"], 1)
        self.assertEqual(result.metrics["negative_feedback_count"], 1)
        self.assertEqual(result.metrics["ignored_feedback_count"], 1)
        self.assertEqual(result.verdict, "pass")

    def test_validate_report_combines_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            report = validate_report(store)

        self.assertIn("Sporepath Validation Report", report.markdown)
        self.assertIn("Notes Validator", report.markdown)
        self.assertIn("Inspire Validator", report.markdown)
        self.assertEqual(report.verdict, "needs_data")


if __name__ == "__main__":
    unittest.main()
