import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import time
from pathlib import Path

from sporepath.digest_queue import (
    collect_fragments_from_arcrift_db,
    collect_fragments_from_file,
    collect_fragments_from_files,
    collect_fragments_from_notes_inbox,
    is_off_peak_window,
    process_digest_queue,
)
from sporepath.extractors import ExtractSignal
from sporepath.store import MemoryStore


class DigestQueueTests(unittest.TestCase):
    def test_off_peak_window_handles_same_day_and_overnight_ranges(self):
        self.assertTrue(is_off_peak_window(time(23, 0), "22:00-07:00"))
        self.assertTrue(is_off_peak_window(time(6, 30), "22:00-07:00"))
        self.assertFalse(is_off_peak_window(time(12, 0), "22:00-07:00"))
        self.assertTrue(is_off_peak_window(time(12, 0), "09:00-17:00"))
        self.assertFalse(is_off_peak_window(time(20, 0), "09:00-17:00"))

    def test_queue_processes_fragments_with_checkpoint(self):
        class FakeExtractor:
            def extract(self, text, role="unknown"):
                if "skip" in text:
                    return ExtractSignal(
                        keep=False,
                        kind="note",
                        summary="",
                        tags=["skip"],
                        confidence=0.2,
                        reason="not reusable",
                    )
                return ExtractSignal(
                    keep=True,
                    kind="idea",
                    summary="Queued useful memory",
                    tags=["queue", "memory"],
                    confidence=0.9,
                    reason="reusable idea",
                    route="idea",
                    signals=["queued memory"],
                    noise=[],
                    handoff="Use this when testing background digestion.",
                )

        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "keep this useful queue memory"}, ensure_ascii=False),
                        json.dumps({"role": "user", "content": "skip this transient line"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            fragments = collect_fragments_from_file(chat, min_chars=5)

            inserted = store.enqueue_fragments(fragments)
            result = process_digest_queue(store, extractor=FakeExtractor(), limit=10)
            atoms = store.list_atoms()
            stats = store.queue_stats()

        self.assertEqual(inserted, 2)
        self.assertEqual(result.processed, 2)
        self.assertEqual(result.atoms_created, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0].metadata["queue_status"], "done")
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats.get("pending", 0), 0)

    def test_queue_records_extractor_errors_without_blocking_other_items(self):
        class FlakyExtractor:
            def extract(self, text, role="unknown"):
                if "boom" in text:
                    raise RuntimeError("model failed")
                return ExtractSignal(
                    keep=True,
                    kind="idea",
                    summary="Survived",
                    tags=["queue"],
                    confidence=0.8,
                    reason="ok",
                )

        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "boom item should be marked error"}, ensure_ascii=False),
                        json.dumps({"role": "user", "content": "normal item should still finish"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )
            store = MemoryStore(Path(tmp) / "memory.sqlite")
            store.enqueue_fragments(collect_fragments_from_file(chat, min_chars=5))

            result = process_digest_queue(store, extractor=FlakyExtractor(), limit=10)
            stats = store.queue_stats()
            errors = store.queue_errors()
            reset_count = store.reset_queue_errors([errors[0]["id"]])
            retried_stats = store.queue_stats()

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.atoms_created, 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["last_error"], "model failed")
        self.assertEqual(reset_count, 1)
        self.assertEqual(retried_stats.get("error", 0), 0)
        self.assertEqual(retried_stats["pending"], 1)
        self.assertEqual(retried_stats["done"], 1)

    def test_queue_collection_dedupes_and_filters_disposable_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.jsonl"
            second = Path(tmp) / "b.jsonl"
            duplicate = "Add support for TSV input. Keep python3 -m pytest -q green."
            first.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": duplicate}),
                        json.dumps(
                            {
                                "role": "user",
                                "content": "<command-name>/remote-control</command-name> <command-message>remote-control</command-message>",
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            second.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": duplicate}),
                        json.dumps({"role": "user", "content": "Add export command for notes as JSON."}),
                    ]
                ),
                encoding="utf-8",
            )

            fragments = collect_fragments_from_files([first, second], min_chars=5)

        self.assertEqual(len(fragments), 2)
        self.assertEqual([fragment["text"] for fragment in fragments].count(duplicate), 1)
        self.assertFalse(any("remote-control" in fragment["text"] for fragment in fragments))

    def test_collect_fragments_from_arcrift_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db)

            fragments = collect_fragments_from_arcrift_db(arcrift_db, min_chars=5)

        self.assertEqual(len(fragments), 2)
        self.assertEqual([fragment["role"] for fragment in fragments], ["user", "assistant"])
        self.assertEqual(fragments[0]["source"], "arcrift:auto-session:turn[0]")
        self.assertEqual(fragments[0]["source_file"], str(arcrift_db))
        self.assertIn("captures the conversation", fragments[0]["text"])

    def test_arcrift_queue_fragments_checkpoint_after_first_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp:
            arcrift_db = Path(tmp) / "ArcRift.db"
            memory_db = Path(tmp) / "memory.sqlite"
            _create_arcrift_db(arcrift_db)
            store = MemoryStore(memory_db)

            fragments = collect_fragments_from_arcrift_db(arcrift_db, min_chars=5)
            first_inserted = store.enqueue_fragments(fragments)
            second_inserted = store.enqueue_fragments(fragments)
            stats = store.queue_stats()

        self.assertEqual(first_inserted, 2)
        self.assertEqual(second_inserted, 0)
        self.assertEqual(stats["pending"], 2)

    def test_collect_fragments_from_notes_inbox_splits_markdown_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "Inbox"
            inbox.mkdir()
            (inbox / "idea.md").write_text(
                "---\ntitle: private metadata\n---\n\n"
                "# Product Idea\n\n"
                "Sporepath should digest old handwritten notes without treating generated vault notes as source truth.\n\n"
                "- Keep the scout small.\n"
                "- Let usage signals decide what survives.\n\n"
                "A short line.\n",
                encoding="utf-8",
            )
            (inbox / "saved.txt").write_text(
                "Saved fragment from an old chat export should become a queue candidate.\n\n"
                "tiny\n",
                encoding="utf-8",
            )
            ignored = inbox / ".sporepath"
            ignored.mkdir()
            (ignored / "manifest.md").write_text("Generated metadata should be ignored.", encoding="utf-8")

            fragments = collect_fragments_from_notes_inbox([inbox], min_chars=30)

        self.assertEqual(len(fragments), 3)
        self.assertEqual({fragment["role"] for fragment in fragments}, {"note"})
        self.assertTrue(all(str(fragment["source"]).startswith("note-inbox:") for fragment in fragments))
        self.assertTrue(any("Product Idea" in str(fragment["text"]) for fragment in fragments))
        self.assertFalse(any("private metadata" in str(fragment["text"]) for fragment in fragments))
        self.assertFalse(any("Generated metadata" in str(fragment["text"]) for fragment in fragments))

    def test_notes_inbox_queue_fragments_checkpoint_after_first_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "Inbox"
            memory_db = Path(tmp) / "memory.sqlite"
            inbox.mkdir()
            (inbox / "note.md").write_text(
                "# Old Note\n\nThis old note should be digested once and not repeatedly requeued.",
                encoding="utf-8",
            )
            store = MemoryStore(memory_db)

            fragments = collect_fragments_from_notes_inbox([inbox], min_chars=20)
            first_inserted = store.enqueue_fragments(fragments)
            second_inserted = store.enqueue_fragments(fragments)
            stats = store.queue_stats()

        self.assertEqual(first_inserted, 1)
        self.assertEqual(second_inserted, 0)
        self.assertEqual(stats["pending"], 1)

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


if __name__ == "__main__":
    unittest.main()
