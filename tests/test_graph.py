import tempfile
import unittest
from pathlib import Path

from sporepath.graph_export import export_graph_html, graph_payload
from sporepath.models import ThoughtAtom
from sporepath.store import MemoryStore


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

    def test_graph_payload_marks_inspire_feedback_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_atoms(
                [
                    make_atom("focus", "Scout eval", ["scout"], 0.5),
                    make_atom("latent", "Go bridge", ["go"], 0.2, "analogy"),
                ]
            )
            run_id = store.record_inspire_run(
                question="How should this bridge be tested?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="Use the go bridge.",
            )
            store.apply_inspire_feedback(
                run_id,
                atom_ids=["focus", "latent"],
                status="applied",
                note="This bridge changed the next step.",
            )

            payload = graph_payload(store, limit=10)
            edge = payload["edges"][0]

        self.assertEqual(edge["relation"], "inspire_feedback")
        self.assertEqual(edge["type"], "inspire_feedback")
        self.assertEqual(edge["status"], "applied")
        self.assertGreater(edge["confidence"], 0)
        self.assertEqual(edge["evidence"]["run_id"], run_id)

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

    def test_export_graph_html_labels_inspire_feedback_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            out = Path(tmp) / "graph.html"
            store.upsert_atoms(
                [
                    make_atom("focus", "Scout eval", ["scout"], 0.5),
                    make_atom("latent", "Go bridge", ["go"], 0.2, "analogy"),
                ]
            )
            run_id = store.record_inspire_run(
                question="How should this bridge be tested?",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="Use the go bridge.",
            )
            store.apply_inspire_feedback(
                run_id,
                atom_ids=["focus", "latent"],
                status="useful",
                note="This bridge changed the next step.",
            )

            export_graph_html(store, out, limit=10)
            html = out.read_text(encoding="utf-8")

        self.assertIn("Inspire bridge", html)
        self.assertIn("pickEdge", html)
        self.assertIn("showEdgeDetails", html)
        self.assertIn("inspire_feedback", html)
        self.assertIn("This bridge changed the next step.", html)


if __name__ == "__main__":
    unittest.main()
