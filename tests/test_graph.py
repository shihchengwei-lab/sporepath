import tempfile
import unittest
from pathlib import Path

from latent_brain.graph_export import export_graph_html, graph_payload
from latent_brain.models import ThoughtAtom
from latent_brain.store import MemoryStore


def make_atom(atom_id, summary, tags, activation, kind="idea"):
    return ThoughtAtom(
        id=atom_id,
        source=f"sample:{atom_id}",
        role="user",
        text=f"Original text for {summary}",
        summary=summary,
        kind=kind,
        tags=tags,
        timestamp="2026-06-24T12:00:00",
        importance=0.7,
        activation=activation,
        metadata={},
    )


class GraphExportTests(unittest.TestCase):
    def test_graph_payload_contains_nodes_and_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    make_atom("active", "Active path", ["poc", "focus"], 0.9),
                    make_atom("latent", "Latent path", ["poc", "latent"], 0.2, "analogy"),
                ]
            )
            store.rebuild_edges()

            payload = graph_payload(store, limit=10)

        self.assertEqual(len(payload["nodes"]), 2)
        self.assertEqual(len(payload["edges"]), 1)
        active = next(node for node in payload["nodes"] if node["id"] == "active")
        latent = next(node for node in payload["nodes"] if node["id"] == "latent")
        self.assertEqual(active["state"], "focus")
        self.assertEqual(latent["state"], "latent")

    def test_export_graph_html_writes_interactive_canvas_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            out = Path(tmp) / "graph.html"
            store.upsert_atoms(
                [
                    make_atom("active", "Active path", ["poc", "focus"], 0.9),
                    make_atom("latent", "Latent path", ["poc", "latent"], 0.2, "analogy"),
                ]
            )
            store.rebuild_edges()

            export_graph_html(store, out, limit=10)
            html = out.read_text(encoding="utf-8")

        self.assertIn("<canvas id=\"graphCanvas\"", html)
        self.assertIn("window.LATENT_BRAIN_GRAPH", html)
        self.assertIn("Active path", html)
        self.assertIn("Latent path", html)
        self.assertIn("Focus", html)
        self.assertIn("Latent", html)


if __name__ == "__main__":
    unittest.main()
