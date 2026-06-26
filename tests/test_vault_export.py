import json
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from pathlib import Path

from sporepath.cli import main
from sporepath.models import DigestedNote
from sporepath.store import MemoryStore
from sporepath.vault_export import export_obsidian_vault


class VaultExportTests(unittest.TestCase):
    def test_exports_notes_as_obsidian_markdown_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.upsert_notes(
                [
                    DigestedNote(
                        id="note1234567890",
                        title="Concept note: memory metabolism",
                        note_type="concept_note",
                        summary="Readable notes sit between raw chat and atoms.",
                        key_points=[
                            "Raw conversations are too long to review",
                            "Thought atoms are too small to read directly",
                        ],
                        open_questions=["How should dormant notes wake up?"],
                        tags=["second-brain", "memory-metabolism"],
                        source_atom_ids=["a1", "a2"],
                        source_spans=["chat.jsonl:line[1]", "chat.jsonl:line[2]"],
                        activation=0.72,
                        metadata={"builder": "rules"},
                    )
                ]
            )
            vault = Path(tmp) / "Sporepath Vault"

            result = export_obsidian_vault(store, vault)

            note_path = vault / "Digested Notes" / "concept-note-memory-metabolism-note123.md"
            manifest_path = vault / ".sporepath" / "manifest.json"

            self.assertEqual(result.notes_exported, 1)
            self.assertTrue(note_path.exists())
            text = note_path.read_text(encoding="utf-8")
            self.assertIn('sporepath_id: "note1234567890"', text)
            self.assertIn('type: "concept_note"', text)
            self.assertIn("activation: 0.72", text)
            self.assertIn('- "second-brain"', text)
            self.assertIn("# Concept note: memory metabolism", text)
            self.assertIn("## Key Points", text)
            self.assertIn("- Raw conversations are too long to review", text)
            self.assertIn("## Open Questions", text)
            self.assertIn("- How should dormant notes wake up?", text)
            self.assertIn("## Sources", text)
            self.assertIn("- `chat.jsonl:line[1]`", text)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["notes_exported"], 1)
            self.assertEqual(
                manifest["notes"][0]["path"],
                "Digested Notes/concept-note-memory-metabolism-note123.md",
            )

    def test_export_requires_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")

            with self.assertRaisesRegex(ValueError, "no digested notes"):
                export_obsidian_vault(store, Path(tmp) / "Vault")

    def test_cli_exports_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            vault = Path(tmp) / "Vault"
            store = MemoryStore(db)
            store.upsert_notes(
                [
                    DigestedNote(
                        id="notecli123456",
                        title="Decision note: notes as byproduct",
                        note_type="decision_note",
                        summary="Notes should be generated after chat.",
                        key_points=["Notes are output, not input"],
                        open_questions=[],
                        tags=["notes"],
                        source_atom_ids=["a1"],
                        source_spans=["chat.jsonl:line[3]"],
                        activation=0.5,
                        metadata={},
                    )
                ]
            )
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["--db", str(db), "export-vault", str(vault)])
            exported_note_exists = (
                vault / "Digested Notes" / "decision-note-notes-as-byproduct-notecli.md"
            ).exists()

        self.assertEqual(code, 0)
        self.assertIn("Exported 1 notes", out.getvalue())
        self.assertTrue(exported_note_exists)


if __name__ == "__main__":
    unittest.main()
