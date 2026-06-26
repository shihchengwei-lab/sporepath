import json
import tempfile
import unittest
from datetime import time
from pathlib import Path

from sporepath.digest_queue import collect_fragments_from_file, is_off_peak_window, process_digest_queue
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

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.atoms_created, 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(stats["done"], 1)


if __name__ == "__main__":
    unittest.main()
