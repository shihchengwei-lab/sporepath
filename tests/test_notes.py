import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.models import DigestedNote, ThoughtAtom
from sporepath.notes import build_notes_from_atoms
from sporepath.store import MemoryStore


def make_atom(atom_id, summary, kind="idea", tags=None, activation=0.4):
    return ThoughtAtom(
        id=atom_id,
        source=f"chat.jsonl:line[{atom_id}]",
        role="user",
        text=f"{summary} full source text",
        summary=summary,
        kind=kind,
        tags=tags or ["second-brain"],
        timestamp="2026-06-26T12:00:00",
        importance=0.7,
        activation=activation,
        metadata={},
    )


class NoteBuilderTests(unittest.TestCase):
    def test_builds_readable_notes_from_atoms_with_sources(self):
        atoms = [
            make_atom("a1", "Memory paths should thicken when reused"),
            make_atom("a2", "Dormant ideas should sink instead of being deleted"),
            make_atom("a3", "How should users inspect old AI chats?", kind="question"),
        ]

        notes = build_notes_from_atoms(atoms, min_atoms=2)

        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note.note_type, "concept_note")
        self.assertIn("second-brain", note.tags)
        self.assertIn("Memory paths should thicken when reused", note.key_points)
        self.assertIn("How should users inspect old AI chats?", note.open_questions)
        self.assertEqual(note.source_atom_ids, ["a1", "a2", "a3"])
        self.assertIn("chat.jsonl:line[a1]", note.source_spans)

    def test_store_round_trips_notes_and_counts_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            note = DigestedNote(
                id="note1",
                title="Concept note: second-brain",
                note_type="concept_note",
                summary="A readable note summary",
                key_points=["First point"],
                open_questions=["Open question"],
                tags=["second-brain"],
                source_atom_ids=["a1"],
                source_spans=["chat.jsonl:line[1]"],
                activation=0.5,
                metadata={"builder": "test"},
            )

            count = store.upsert_notes([note])
            loaded = store.get_note("note1")
            stats = store.stats()

        self.assertEqual(count, 1)
        self.assertEqual(loaded.title, "Concept note: second-brain")
        self.assertEqual(loaded.key_points, ["First point"])
        self.assertEqual(stats["notes"], 1)

    def test_cli_digest_lists_and_shows_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    make_atom("a1", "AI chats need a readable middle layer"),
                    make_atom("a2", "Thought atoms are too small for review"),
                ]
            )
            store.upsert_notes(
                [
                    DigestedNote(
                        id="stale",
                        title="Old note",
                        note_type="concept_note",
                        summary="This should disappear",
                        key_points=["stale"],
                        open_questions=[],
                        tags=["old"],
                        source_atom_ids=["old"],
                        source_spans=["old"],
                        activation=0.1,
                        metadata={},
                    )
                ]
            )

            digest_out = io.StringIO()
            with redirect_stdout(digest_out):
                digest_code = main(["--db", str(db), "digest", "--min-atoms", "2"])

            list_out = io.StringIO()
            with redirect_stdout(list_out):
                list_code = main(["--db", str(db), "notes"])

            note_id = store.list_notes()[0].id
            show_out = io.StringIO()
            with redirect_stdout(show_out):
                show_code = main(["--db", str(db), "show-note", note_id])

            stale_removed = False
            try:
                store.get_note("stale")
            except KeyError:
                stale_removed = True

        self.assertEqual(digest_code, 0)
        self.assertTrue(stale_removed)
        self.assertEqual(list_code, 0)
        self.assertEqual(show_code, 0)
        self.assertIn("Built 1 digested notes", digest_out.getvalue())
        self.assertIn("concept_note", list_out.getvalue())
        self.assertIn("AI chats need a readable middle layer", show_out.getvalue())
        self.assertIn("source atoms:", show_out.getvalue())


if __name__ == "__main__":
    unittest.main()
