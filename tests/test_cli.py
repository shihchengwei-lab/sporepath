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

    def test_eval_extract_help_exposes_ollama_budget_args(self):
        out = io.StringIO()

        with self.assertRaises(SystemExit) as raised, redirect_stdout(out):
            main(["eval-extract", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--ollama-timeout-s", out.getvalue())
        self.assertIn("--ollama-num-predict", out.getvalue())

    def test_queue_build_and_digest_queue_process_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            chat = Path(tmp) / "chat.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "第一個 queue idea 要離峰整理。"}, ensure_ascii=False),
                        json.dumps({"role": "user", "content": "第二個 queue idea 先留在 backlog。"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                build_code = main(["--db", str(db), "queue-build", "--input", str(chat), "--min-chars", "5"])
            with redirect_stdout(out):
                digest_code = main(["--db", str(db), "digest-queue", "--extractor", "rules", "--limit", "1"])
            store = MemoryStore(db)
            stats = store.queue_stats()
            atoms = store.list_atoms()

        self.assertEqual(build_code, 0)
        self.assertEqual(digest_code, 0)
        self.assertIn("Enqueued 2 fragments", out.getvalue())
        self.assertIn("processed=1", out.getvalue())
        self.assertEqual(len(atoms), 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["pending"], 1)

    def test_inspire_feedback_command_strengthens_selected_atoms(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="a1",
                        source="sample.jsonl:line[1]",
                        role="user",
                        text="小模型是 scout。",
                        summary="小模型 scout",
                        kind="idea",
                        tags=["scout"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="a2",
                        source="sample.jsonl:line[2]",
                        role="user",
                        text="神之一手來自遠處弱連結。",
                        summary="遠處弱連結",
                        kind="analogy",
                        tags=["go"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            run_id = store.record_inspire_run(
                question="如何驗證 scout？",
                focus_atom_ids=["a1"],
                latent_atom_ids=["a2"],
                output_text="用遠處弱連結做 eval。",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "inspire-feedback",
                        run_id,
                        "--status",
                        "applied",
                        "--atoms",
                        "a1",
                        "a2",
                    ]
                )
            refreshed = MemoryStore(db)
            edges = refreshed.list_edges()

        self.assertEqual(code, 0)
        self.assertIn("bridges_strengthened=1", out.getvalue())
        self.assertEqual(edges[0].relation, "inspire_feedback")

    def test_inspire_feedback_command_accepts_suggestion_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="a1",
                        source="sample.jsonl:line[1]",
                        role="user",
                        text="Small model is only the scout.",
                        summary="Small model scout",
                        kind="idea",
                        tags=["scout"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="a2",
                        source="sample.jsonl:line[2]",
                        role="user",
                        text="Cloud model decides whether the bridge sparks.",
                        summary="Cloud model bridge spark",
                        kind="idea",
                        tags=["spark"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            run_id = store.record_inspire_run(
                question="How do I validate the split?",
                focus_atom_ids=["a1"],
                latent_atom_ids=["a2"],
                output_text="suggestion_id: 1\ncited_atom_ids: [a1, a2]",
            )
            store.record_inspire_suggestions(
                run_id,
                [
                    {
                        "suggestion_id": "1",
                        "cited_atom_ids": ["a1", "a2"],
                        "text": "Use this split as the eval.",
                    }
                ],
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "inspire-feedback",
                        run_id,
                        "--status",
                        "selected",
                        "--suggestion",
                        "1",
                    ]
                )
            refreshed = MemoryStore(db)
            edges = refreshed.list_edges()

        self.assertEqual(code, 0)
        self.assertIn("suggestion=1", out.getvalue())
        self.assertEqual(edges[0].relation, "inspire_feedback")


if __name__ == "__main__":
    unittest.main()
