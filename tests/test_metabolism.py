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


if __name__ == "__main__":
    unittest.main()
