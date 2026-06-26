import tempfile
import unittest
from pathlib import Path

from sporepath.models import ThoughtAtom
from sporepath.store import MemoryStore


class MetabolismTests(unittest.TestCase):
    def test_touch_strengthens_and_decay_weakens_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            atom = ThoughtAtom(
                id="a1",
                source="test:1",
                role="user",
                text="常用的 AI memory 路徑應該加粗。",
                summary="常用路徑加粗",
                kind="idea",
                tags=["ai-memory"],
                timestamp="2026-06-24T12:00:00",
                importance=0.6,
                activation=0.2,
                metadata={},
            )
            store.upsert_atoms([atom])

            store.touch_atoms(["a1"], amount=0.5)
            strengthened = store.get_atom("a1")
            self.assertGreaterEqual(strengthened.activation, 0.69)

            store.decay_all(factor=0.5, floor=0.1)
            decayed = store.get_atom("a1")
            self.assertLess(decayed.activation, strengthened.activation)
            self.assertGreaterEqual(decayed.activation, 0.1)

    def test_focus_prefers_active_recent_atoms(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="active",
                        source="test:active",
                        role="user",
                        text="最近一直在研究本地第二大腦。",
                        summary="本地第二大腦",
                        kind="idea",
                        tags=["second-brain"],
                        timestamp="2026-06-24T12:00:00",
                        importance=0.6,
                        activation=0.9,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="latent",
                        source="test:latent",
                        role="user",
                        text="很久以前提過圍棋神之一手。",
                        summary="神之一手",
                        kind="analogy",
                        tags=["go"],
                        timestamp="2026-01-01T12:00:00",
                        importance=0.7,
                        activation=0.15,
                        metadata={},
                    ),
                ]
            )

            focus = store.focus_atoms(limit=1)
            latent = store.latent_candidates("卡在創意突破", limit=5)

        self.assertEqual(focus[0].id, "active")
        self.assertEqual(latent[0].id, "latent")

    def test_latent_candidates_include_weird_low_importance_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="reliable",
                        source="test:reliable",
                        role="user",
                        text="High importance forgotten memory about AI notes.",
                        summary="High importance forgotten memory",
                        kind="idea",
                        tags=["ai-memory"],
                        timestamp=None,
                        importance=0.92,
                        activation=0.08,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="boring",
                        source="test:boring",
                        role="user",
                        text="Another important but unrelated archived memory.",
                        summary="Another important archived memory",
                        kind="idea",
                        tags=["archive"],
                        timestamp=None,
                        importance=0.95,
                        activation=0.05,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="weird",
                        source="test:weird",
                        role="user",
                        text="A small packaging ritual might unlock the product story.",
                        summary="Packaging ritual unlocks product story",
                        kind="analogy",
                        tags=["ritual"],
                        timestamp=None,
                        importance=0.18,
                        activation=0.01,
                        metadata={},
                    ),
                ]
            )

            candidates = store.latent_candidates("Need a packaging ritual idea", limit=2)

        self.assertIn("weird", [atom.id for atom in candidates])

    def test_edges_include_evidence_and_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="a1",
                        source="chat.jsonl:line[1]",
                        role="user",
                        text="First idea",
                        summary="First idea",
                        kind="idea",
                        tags=["shared", "alpha"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.3,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="a2",
                        source="chat.jsonl:line[2]",
                        role="user",
                        text="Second idea",
                        summary="Second idea",
                        kind="idea",
                        tags=["shared", "beta"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.3,
                        metadata={},
                    ),
                ]
            )

            store.rebuild_edges()
            edges = store.list_edges()

        self.assertEqual(len(edges), 1)
        self.assertGreater(edges[0].confidence, 0)
        self.assertIn("shared", edges[0].evidence["shared_tags"])

    def test_inspire_feedback_strengthens_atoms_and_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="focus",
                        source="chat.jsonl:line[1]",
                        role="user",
                        text="正在做小模型 scout eval。",
                        summary="小模型 scout eval",
                        kind="idea",
                        tags=["eval"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="latent",
                        source="chat.jsonl:line[2]",
                        role="user",
                        text="圍棋神之一手是遠處弱連結。",
                        summary="遠處弱連結",
                        kind="analogy",
                        tags=["go"],
                        timestamp=None,
                        importance=0.4,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            run_id = store.record_inspire_run(
                question="怎麼驗證 scout 有價值？",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="用圍棋殘局測試 scout handoff。",
            )

            result = store.apply_inspire_feedback(
                run_id,
                atom_ids=["focus", "latent"],
                status="useful",
                note="這條橋有用",
                amount=0.2,
            )
            focus = store.get_atom("focus")
            latent = store.get_atom("latent")
            edges = store.list_edges()

            self.assertEqual(result["atoms_touched"], 2)
            self.assertEqual(result["bridges_strengthened"], 1)
            self.assertGreater(focus.activation, 0.2)
            self.assertGreater(latent.activation, 0.1)
            self.assertEqual(edges[0].relation, "inspire_feedback")
            self.assertEqual(edges[0].evidence["status"], "useful")
            self.assertEqual(edges[0].evidence["run_id"], run_id)

            store.rebuild_edges()
            relations = [edge.relation for edge in store.list_edges()]

        self.assertIn("inspire_feedback", relations)

    def test_inspire_feedback_can_use_stored_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="focus",
                        source="chat.jsonl:line[1]",
                        role="user",
                        text="Small model scout writes the first atom.",
                        summary="Small model scout atom",
                        kind="idea",
                        tags=["scout"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="latent",
                        source="chat.jsonl:line[2]",
                        role="user",
                        text="A weak bridge can become useful later.",
                        summary="Weak bridge later becomes useful",
                        kind="analogy",
                        tags=["bridge"],
                        timestamp=None,
                        importance=0.4,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            run_id = store.record_inspire_run(
                question="How do I validate sparks?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="suggestion_id: 1\ncited_atom_ids: [focus, latent]",
            )
            store.record_inspire_suggestions(
                run_id,
                [
                    {
                        "suggestion_id": "1",
                        "cited_atom_ids": ["focus", "latent"],
                        "text": "Use the weak bridge as the eval case.",
                    }
                ],
            )

            result = store.apply_inspire_feedback(
                run_id,
                suggestion_id="1",
                status="selected",
            )
            edges = store.list_edges()

        self.assertEqual(result["atoms_touched"], 2)
        self.assertEqual(result["bridges_strengthened"], 1)
        self.assertEqual(edges[0].evidence["suggestion_id"], "1")

    def test_latent_candidates_prefer_feedback_bridge_from_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="focus",
                        source="chat.jsonl:line[1]",
                        role="user",
                        text="I am focused on validating scout quality.",
                        summary="Validate scout quality",
                        kind="idea",
                        tags=["scout"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.9,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="bridged",
                        source="chat.jsonl:line[2]",
                        role="user",
                        text="A ritual metaphor helped test the product story.",
                        summary="Ritual metaphor for product story",
                        kind="analogy",
                        tags=["ritual"],
                        timestamp=None,
                        importance=0.2,
                        activation=0.1,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="unbridged",
                        source="chat.jsonl:line[3]",
                        role="user",
                        text="A high importance archived implementation note.",
                        summary="High importance implementation note",
                        kind="idea",
                        tags=["implementation"],
                        timestamp=None,
                        importance=0.95,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            run_id = store.record_inspire_run(
                question="How do I validate scout quality?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["bridged"],
                output_text="suggestion_id: 1\ncited_atom_ids: [focus, bridged]",
            )
            store.apply_inspire_feedback(
                run_id,
                atom_ids=["focus", "bridged"],
                status="applied",
                amount=0.4,
            )
            store.decay_all(factor=0.2, floor=0.05)

            candidates = store.latent_candidates(
                "How do I validate scout quality?",
                limit=1,
                focus_atom_ids=["focus"],
            )

        self.assertEqual(candidates[0].id, "bridged")


if __name__ == "__main__":
    unittest.main()
