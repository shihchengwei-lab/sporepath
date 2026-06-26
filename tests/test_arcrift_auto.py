import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from sporepath.automation import default_arcrift_db_path, sync_arcrift_memory
from sporepath.cli import main, should_sync_arcrift_tick
from sporepath.source_watch import SourceSnapshot, sqlite_watch_paths
from sporepath.store import MemoryStore


class ArcRiftAutoTests(unittest.TestCase):
    def test_default_arcrift_db_path_prefers_neighbor_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sporepath = root / "sporepath"
            arcrift_db = root / "ArcRift" / "backend" / "ArcRift.db"
            arcrift_db.parent.mkdir(parents=True)
            arcrift_db.write_bytes(b"sqlite placeholder")

            detected = default_arcrift_db_path(cwd=sporepath, home=root / "home")

        self.assertEqual(detected, arcrift_db)

    def test_sync_arcrift_memory_imports_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            memory_db = Path(tmp) / "memory.sqlite"
            vault = Path(tmp) / "Vault"
            graph = Path(tmp) / "graph.html"
            _create_arcrift_db(arcrift_db)

            result = sync_arcrift_memory(
                db_path=memory_db,
                arcrift_db_path=arcrift_db,
                vault_path=vault,
                graph_path=graph,
                min_note_atoms=1,
            )

            self.assertEqual(result.atoms_imported, 2)
            self.assertEqual(result.atoms_after, 2)
            self.assertGreaterEqual(result.notes_built, 1)
            self.assertTrue((vault / ".sporepath" / "manifest.json").exists())
            self.assertTrue(graph.exists())

    def test_cli_sync_arcrift_runs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            memory_db = Path(tmp) / "memory.sqlite"
            vault = Path(tmp) / "Vault"
            graph = Path(tmp) / "graph.html"
            _create_arcrift_db(arcrift_db)
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(memory_db),
                        "sync-arcrift",
                        "--arcrift-db",
                        str(arcrift_db),
                        "--vault",
                        str(vault),
                        "--graph",
                        str(graph),
                        "--min-note-atoms",
                        "1",
                    ]
                )
            atoms = MemoryStore(memory_db).list_atoms()

        self.assertEqual(code, 0)
        self.assertEqual(len(atoms), 2)
        self.assertIn("ArcRift sync complete", out.getvalue())

    def test_cli_watch_arcrift_once_uses_same_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            memory_db = Path(tmp) / "memory.sqlite"
            _create_arcrift_db(arcrift_db)
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(memory_db),
                        "watch-arcrift",
                        "--arcrift-db",
                        str(arcrift_db),
                        "--once",
                        "--min-note-atoms",
                        "1",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("ArcRift sync complete", out.getvalue())

    def test_watch_arcrift_tick_skips_when_db_snapshot_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db)
            snapshot = SourceSnapshot.from_paths(sqlite_watch_paths(arcrift_db))

            should_sync, next_snapshot = should_sync_arcrift_tick(
                snapshot,
                arcrift_db,
                force=False,
            )

        self.assertFalse(should_sync)
        self.assertEqual(next_snapshot, snapshot)

    def test_watch_arcrift_tick_syncs_when_wal_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db)
            snapshot = SourceSnapshot.from_paths(sqlite_watch_paths(arcrift_db))
            Path(str(arcrift_db) + "-wal").write_text("changed", encoding="utf-8")

            should_sync, next_snapshot = should_sync_arcrift_tick(
                snapshot,
                arcrift_db,
                force=False,
            )

        self.assertTrue(should_sync)
        self.assertNotEqual(next_snapshot, snapshot)


def _create_arcrift_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.executescript(
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
            );
            CREATE TABLE full_chats (
                sessionId TEXT PRIMARY KEY,
                rawText TEXT NOT NULL,
                processedText TEXT,
                messageCount INTEGER DEFAULT 0,
                platform TEXT,
                createdAt TEXT
            );
            """
        )
        con.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "auto-session",
                "Automation Trial",
                "chatgpt",
                "Synthetic ArcRift session",
                0,
                0,
                1,
                "2026-06-26T00:00:00Z",
                "2026-06-26T00:01:00Z",
                None,
            ),
        )
        con.execute(
            "INSERT INTO full_chats VALUES (?, ?, ?, ?, ?, ?)",
            (
                "auto-session",
                "[User]: ArcRift captures the conversation.\n\n"
                "[Assistant]: Sporepath should digest it into Obsidian notes automatically.",
                None,
                2,
                "chatgpt",
                "2026-06-26T00:00:00Z",
            ),
        )
        con.commit()
