import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.models import ThoughtAtom
from sporepath.store import MemoryStore


class CliTests(unittest.TestCase):
    def test_inspire_empty_db_stops_before_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.sqlite"
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["--db", str(db), "inspire", "我卡住了"])

        self.assertEqual(code, 2)
        self.assertIn("memory database is empty", out.getvalue())
        self.assertIn("ingest", out.getvalue())

    def test_show_prints_original_atom_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="abc123",
                        source="sample.jsonl:line[7]",
                        role="user",
                        text="這是原始想法，不是摘要。",
                        summary="原始想法",
                        kind="idea",
                        tags=["poc"],
                        timestamp="2026-06-24T12:00:00",
                        importance=0.7,
                        activation=0.3,
                        metadata={"extractor_confidence": 0.88, "extractor_reason": "可重用"},
                    )
                ]
            )
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["--db", str(db), "show", "abc123"])

        self.assertEqual(code, 0)
        self.assertIn("sample.jsonl:line[7]", out.getvalue())
        self.assertIn("這是原始想法，不是摘要。", out.getvalue())
        self.assertIn("extractor_confidence", out.getvalue())

    def test_graph_command_writes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            out_path = Path(tmp) / "graph.html"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="abc123",
                        source="sample.jsonl:line[7]",
                        role="user",
                        text="可視化測試原文。",
                        summary="可視化測試",
                        kind="idea",
                        tags=["poc"],
                        timestamp="2026-06-24T12:00:00",
                        importance=0.7,
                        activation=0.8,
                        metadata={},
                    )
                ]
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "graph", "--out", str(out_path)])

            self.assertEqual(code, 0)
            self.assertTrue(out_path.exists())
            self.assertIn("可視化測試", out_path.read_text(encoding="utf-8"))

    def test_ingest_respects_max_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            chat = Path(tmp) / "chat.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"role": "user", "content": "第一個 PoC 想法要留下。"},
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {"role": "user", "content": "第二個 PoC 想法不應被讀到。"},
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "ingest", str(chat), "--max-turns", "1"])
            store = MemoryStore(db)
            atoms = store.list_atoms()

        self.assertEqual(code, 0)
        self.assertEqual(len(atoms), 1)
        self.assertIn("第一個", atoms[0].text)


if __name__ == "__main__":
    unittest.main()
