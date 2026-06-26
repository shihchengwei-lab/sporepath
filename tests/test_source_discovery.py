import json
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from pathlib import Path

from sporepath.cli import main
from sporepath.refresh import refresh_memory
from sporepath.source_discovery import discover_sources, expand_source_files
from sporepath.store import MemoryStore


class SourceDiscoveryTests(unittest.TestCase):
    def test_discovers_only_allowlisted_conversation_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex = home / ".codex"
            claude = home / ".claude"
            (codex / "sessions").mkdir(parents=True)
            (claude / "projects").mkdir(parents=True)
            (codex / "history.jsonl").write_text("{}", encoding="utf-8")
            (codex / "auth.json").write_text("{}", encoding="utf-8")
            (codex / "logs_2.sqlite").write_text("nope", encoding="utf-8")
            (claude / "history.jsonl").write_text("{}", encoding="utf-8")
            (claude / ".credentials.json").write_text("{}", encoding="utf-8")
            (claude / "settings.json").write_text("{}", encoding="utf-8")

            sources = discover_sources(home=home)
            labels = {source.label for source in sources}
            paths = {source.path for source in sources}

        self.assertIn("codex_history", labels)
        self.assertIn("codex_sessions", labels)
        self.assertIn("claude_history", labels)
        self.assertIn("claude_projects", labels)
        self.assertNotIn(codex / "auth.json", paths)
        self.assertNotIn(codex / "logs_2.sqlite", paths)
        self.assertNotIn(claude / ".credentials.json", paths)
        self.assertNotIn(claude / "settings.json", paths)

    def test_expands_only_json_and_jsonl_files_inside_source_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            nested = root / "2026" / "06"
            nested.mkdir(parents=True)
            keep = nested / "session.jsonl"
            skip = nested / "auth.json"
            keep.write_text(
                json.dumps({"role": "user", "content": "A useful idea about memory paths"}),
                encoding="utf-8",
            )
            skip.write_text("{}", encoding="utf-8")

            files = expand_source_files([root])

        self.assertEqual(files, [keep])

    def test_refresh_can_ingest_multiple_discovered_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "codex.jsonl"
            second = root / "claude.jsonl"
            first.write_text(
                json.dumps({"role": "user", "content": "Generated notes should reduce review friction"}),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"role": "user", "content": "Obsidian can be the human reading surface"}),
                encoding="utf-8",
            )

            db = root / "memory.sqlite"
            result = refresh_memory(
                db_path=db,
                input_paths=[first, second],
                min_note_atoms=2,
            )
            store = MemoryStore(db)
            note_count = len(store.list_notes())

        self.assertEqual(result.atoms_imported, 2)
        self.assertEqual(result.atoms_after, 2)
        self.assertEqual(note_count, 1)

    def test_sources_cli_lists_detected_sources_from_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".codex").mkdir()
            (home / ".codex" / "history.jsonl").write_text("{}", encoding="utf-8")
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["sources", "--home", str(home)])

        self.assertEqual(code, 0)
        self.assertIn("codex_history", out.getvalue())
        self.assertIn(str(home / ".codex" / "history.jsonl"), out.getvalue())


if __name__ == "__main__":
    unittest.main()
