import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.models import ThoughtAtom
from sporepath.refresh import refresh_memory
from sporepath.store import MemoryStore


def make_atom(atom_id, summary):
    return ThoughtAtom(
        id=atom_id,
        source=f"chat.jsonl:line[{atom_id}]",
        role="user",
        text=f"{summary} full source text",
        summary=summary,
        kind="idea",
        tags=["second-brain"],
        timestamp="2026-06-26T12:00:00",
        importance=0.7,
        activation=0.5,
        metadata={},
    )


class RefreshTests(unittest.TestCase):
    def test_refresh_builds_notes_vault_and_graph_from_existing_atoms(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            vault = Path(tmp) / "Vault"
            graph = Path(tmp) / "graph.html"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    make_atom("a1", "AI chats need generated notes"),
                    make_atom("a2", "Obsidian should be the reading surface"),
                ]
            )

            result = refresh_memory(
                db_path=db,
                vault_path=vault,
                graph_path=graph,
                min_note_atoms=2,
            )

            self.assertEqual(result.atoms_after, 2)
            self.assertEqual(result.notes_built, 1)
            self.assertEqual(result.vault_notes_exported, 1)
            self.assertTrue(graph.exists())
            self.assertTrue((vault / ".sporepath" / "manifest.json").exists())
            self.assertEqual(len(MemoryStore(db).list_notes()), 1)

    def test_refresh_cli_reports_pipeline_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    make_atom("a1", "Refresh should hide command friction"),
                    make_atom("a2", "The app can call the same pipeline"),
                ]
            )
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "refresh",
                        "--vault",
                        str(Path(tmp) / "Vault"),
                        "--graph",
                        str(Path(tmp) / "graph.html"),
                        "--min-note-atoms",
                        "2",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Refresh complete", out.getvalue())
        self.assertIn("notes=1", out.getvalue())

    def test_app_dry_run_prints_default_paths_without_opening_window(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--db", "real_memory.sqlite", "app", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("Sporepath desktop app", out.getvalue())
        self.assertIn("real_memory.sqlite", out.getvalue())


if __name__ == "__main__":
    unittest.main()
