import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.arcrift_import import extract_atoms_from_arcrift_db, parse_arcrift_raw_text
from sporepath.cli import main
from sporepath.store import MemoryStore


class ArcRiftImportTests(unittest.TestCase):
    def test_parse_arcrift_raw_text_splits_tagged_turns(self):
        raw_text = (
            "[User]: I want a second brain that digests AI chats.\n\n"
            "[Assistant]: The main risk is stale notes without feedback.\n\n"
            "[User]: ArcRift can capture while Sporepath metabolizes."
        )

        turns = parse_arcrift_raw_text(raw_text)

        self.assertEqual([turn["role"] for turn in turns], ["user", "assistant", "user"])
        self.assertIn("digests AI chats", turns[0]["text"])
        self.assertIn("Sporepath metabolizes", turns[2]["text"])

    def test_parse_arcrift_raw_text_keeps_mcp_blocks_without_role_tags(self):
        turns = parse_arcrift_raw_text("Remember this product decision for later.")

        self.assertEqual(turns, [{"role": "unknown", "text": "Remember this product decision for later."}])

    def test_extract_atoms_from_arcrift_sqlite_full_chats(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(
                arcrift_db,
                raw_text=(
                    "[User]: I want a local-first memory tool for AI chats.\n\n"
                    "[Assistant]: The strongest companion angle is Obsidian digestion."
                ),
            )

            atoms = extract_atoms_from_arcrift_db(arcrift_db)

        self.assertEqual(len(atoms), 2)
        self.assertEqual([atom.role for atom in atoms], ["user", "assistant"])
        self.assertTrue(all(atom.source.startswith("arcrift:proj-1:turn[") for atom in atoms))
        self.assertEqual(atoms[0].metadata["source_system"], "arcrift")
        self.assertEqual(atoms[0].metadata["arcrift_project"], "Test Project")
        self.assertEqual(atoms[0].metadata["arcrift_platform"], "chatgpt")

    def test_extract_atoms_can_filter_by_project_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db, session_id="keep", project="Keep", raw_text="[User]: Keep this idea.")
            _insert_arcrift_session(arcrift_db, session_id="skip", project="Skip", raw_text="[User]: Skip this idea.")

            atoms = extract_atoms_from_arcrift_db(arcrift_db, project="Keep")

        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0].metadata["arcrift_session_id"], "keep")

    def test_cli_import_arcrift_writes_atoms(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(
                arcrift_db,
                session_id="s1",
                project="ArcRift Test",
                raw_text="[User]: Keep this ArcRift idea for Obsidian digestion.",
            )
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["--db", str(db), "import-arcrift", str(arcrift_db)])
            atoms = MemoryStore(db).list_atoms()

        self.assertEqual(code, 0)
        self.assertEqual(len(atoms), 1)
        self.assertIn("ArcRift", atoms[0].text)
        self.assertIn("Imported 1 ArcRift thought atoms", out.getvalue())


def _create_arcrift_db(
    path: Path,
    *,
    session_id: str = "proj-1",
    project: str = "Test Project",
    raw_text: str,
) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                projectName TEXT NOT NULL,
                platform TEXT,
                summary TEXT,
                tripleCount INTEGER DEFAULT 0,
                topicCount INTEGER DEFAULT 0,
                hasFullChat INTEGER DEFAULT 0,
                createdAt TEXT,
                updatedAt TEXT,
                externalChatId TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE full_chats (
                sessionId TEXT PRIMARY KEY,
                rawText TEXT NOT NULL,
                processedText TEXT,
                messageCount INTEGER DEFAULT 0,
                platform TEXT,
                createdAt TEXT
            )
            """
        )
        con.commit()
    _insert_arcrift_session(path, session_id=session_id, project=project, raw_text=raw_text)


def _insert_arcrift_session(path: Path, *, session_id: str, project: str, raw_text: str) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.execute(
            """
            INSERT INTO sessions
                (id, projectName, platform, summary, tripleCount, topicCount, hasFullChat, createdAt, updatedAt, externalChatId)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                project,
                "chatgpt",
                "A test ArcRift session",
                0,
                0,
                1,
                "2026-06-26T00:00:00.000Z",
                "2026-06-26T00:01:00.000Z",
                None,
            ),
        )
        con.execute(
            """
            INSERT INTO full_chats (sessionId, rawText, processedText, messageCount, platform, createdAt)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, raw_text, None, 1, "chatgpt", "2026-06-26T00:00:00.000Z"),
        )
        con.commit()
