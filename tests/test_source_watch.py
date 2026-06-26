import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.source_discovery import expand_source_files
from sporepath.source_watch import (
    SourceSnapshot,
    build_source_snapshot,
    source_snapshot_changed,
    sqlite_watch_paths,
)
from sporepath.store import MemoryStore


class SourceWatchTests(unittest.TestCase):
    def test_snapshot_tracks_allowed_json_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sessions"
            source_dir.mkdir()
            keep = source_dir / "session.jsonl"
            skip = source_dir / "auth.json"
            keep.write_text(
                json.dumps({"role": "user", "content": "latent memory needs local sources"}),
                encoding="utf-8",
            )
            skip.write_text("{}", encoding="utf-8")

            snapshot = build_source_snapshot([source_dir])

        self.assertEqual(set(snapshot.files), {str(keep)})

    def test_detects_new_modified_and_removed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sessions"
            source_dir.mkdir()
            first = source_dir / "first.jsonl"
            first.write_text(
                json.dumps({"role": "user", "content": "first useful memory"}),
                encoding="utf-8",
            )
            before = build_source_snapshot([source_dir])
            self.assertFalse(source_snapshot_changed(before, [source_dir]))

            first.write_text(
                json.dumps({"role": "user", "content": "first useful memory changed"}),
                encoding="utf-8",
            )
            self.assertTrue(source_snapshot_changed(before, [source_dir]))

            after_modify = build_source_snapshot([source_dir])
            second = source_dir / "second.jsonl"
            second.write_text(
                json.dumps({"role": "user", "content": "second useful memory"}),
                encoding="utf-8",
            )
            self.assertTrue(source_snapshot_changed(after_modify, [source_dir]))

            after_add = build_source_snapshot([source_dir])
            second.unlink()
            self.assertTrue(source_snapshot_changed(after_add, [source_dir]))

    def test_empty_snapshot_is_not_changed_until_allowed_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sessions"
            source_dir.mkdir()
            before = SourceSnapshot.from_paths(expand_source_files([source_dir]))
            (source_dir / "settings.json").write_text("{}", encoding="utf-8")

            self.assertFalse(source_snapshot_changed(before, [source_dir]))

    def test_sqlite_watch_paths_include_wal_and_shm(self):
        db = Path("ArcRift.db")

        self.assertEqual(
            sqlite_watch_paths(db),
            [db, Path("ArcRift.db-wal"), Path("ArcRift.db-shm")],
        )

    def test_sqlite_snapshot_detects_wal_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ArcRift.db"
            db.write_text("db", encoding="utf-8")
            before = SourceSnapshot.from_paths(sqlite_watch_paths(db))

            (Path(str(db) + "-wal")).write_text("wal", encoding="utf-8")
            after = SourceSnapshot.from_paths(sqlite_watch_paths(db))

        self.assertNotEqual(before, after)

    def test_watch_sources_once_refreshes_detected_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex = root / ".codex"
            codex.mkdir()
            (codex / "history.jsonl").write_text(
                json.dumps({"role": "user", "content": "Codex local logs should become notes"}),
                encoding="utf-8",
            )
            db = root / "memory.sqlite"
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "watch-sources",
                        "--source",
                        "codex",
                        "--home",
                        str(root),
                        "--once",
                        "--min-note-atoms",
                        "1",
                    ]
                )

            atoms = MemoryStore(db).list_atoms()

        self.assertEqual(code, 0)
        self.assertEqual(len(atoms), 1)
        self.assertIn("Source sync complete", out.getvalue())


if __name__ == "__main__":
    unittest.main()
