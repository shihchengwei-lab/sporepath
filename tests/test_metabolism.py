import tempfile
import unittest
from pathlib import Path

from latent_brain.models import ThoughtAtom
from latent_brain.store import MemoryStore


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


if __name__ == "__main__":
    unittest.main()
