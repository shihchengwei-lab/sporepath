import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.models import DigestedNote, ThoughtAtom
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
        self.assertIn("--no-dedupe", out.getvalue())
        self.assertIn("--dedupe-threshold", out.getvalue())

    def test_validate_scout_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            report = Path(tmp) / "scout.md"
            sheet.write_text(
                json.dumps(
                    {
                        "id": "good",
                        "text": "Useful memory",
                        "prediction": {"keep": True, "route": "debug", "tags": [], "handoff": "Use it."},
                        "human": {
                            "keep": True,
                            "route": "debug",
                            "signal_found": True,
                            "noise_marked": True,
                            "handoff_sufficient": True,
                            "useful": True,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            out = io.StringIO()

            with redirect_stdout(out):
                code = main(["validate-scout", str(sheet), "--out", str(report)])
            report_exists = report.exists()
            report_text = report.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertTrue(report_exists)
        self.assertIn("Scout Validator", report_text)
        self.assertIn("verdict=", out.getvalue())

    def test_validate_notes_inspire_and_report_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            notes_report = Path(tmp) / "notes.md"
            inspire_report = Path(tmp) / "inspire.md"
            combined_report = Path(tmp) / "report.md"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="a1",
                        source="chat.jsonl:line[1]",
                        role="user",
                        text="Useful memory",
                        summary="Useful memory",
                        kind="idea",
                        tags=["memory"],
                        timestamp=None,
                        importance=0.7,
                        activation=0.5,
                        metadata={},
                    )
                ]
            )
            store.upsert_notes(
                [
                    DigestedNote(
                        id="n1",
                        title="Concept note: memory",
                        note_type="concept_note",
                        summary="Useful note",
                        key_points=["Useful memory"],
                        open_questions=[],
                        tags=["memory"],
                        source_atom_ids=["a1"],
                        source_spans=["chat.jsonl:line[1]"],
                        activation=0.5,
                        metadata={},
                    )
                ]
            )

            with redirect_stdout(io.StringIO()):
                notes_code = main(["--db", str(db), "validate-notes", "--out", str(notes_report)])
            with redirect_stdout(io.StringIO()):
                inspire_code = main(["--db", str(db), "validate-inspire", "--out", str(inspire_report)])
            with redirect_stdout(io.StringIO()):
                report_code = main(["--db", str(db), "validate-report", "--out", str(combined_report)])
            notes_text = notes_report.read_text(encoding="utf-8")
            inspire_text = inspire_report.read_text(encoding="utf-8")
            combined_text = combined_report.read_text(encoding="utf-8")

        self.assertEqual(notes_code, 0)
        self.assertEqual(inspire_code, 0)
        self.assertEqual(report_code, 0)
        self.assertIn("Notes Validator", notes_text)
        self.assertIn("Inspire Validator", inspire_text)
        self.assertIn("Sporepath Validation Report", combined_text)

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

    def test_queue_worker_once_run_now_processes_one_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            chat = Path(tmp) / "chat.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "第一個 worker queue idea。"}, ensure_ascii=False),
                        json.dumps({"role": "user", "content": "第二個 worker queue idea。"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                main(["--db", str(db), "queue-build", "--input", str(chat), "--min-chars", "5"])
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-worker",
                        "--once",
                        "--run-now",
                        "--extractor",
                        "rules",
                        "--batch-size",
                        "1",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()

        self.assertEqual(code, 0)
        self.assertIn("worker_tick=processed", out.getvalue())
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["pending"], 1)

    def test_queue_worker_can_auto_feed_and_refresh_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            chat = Path(tmp) / "chat.jsonl"
            vault = Path(tmp) / "Vault"
            graph = Path(tmp) / "graph.html"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "worker should queue this reusable idea"}, ensure_ascii=False),
                        json.dumps({"role": "user", "content": "worker should leave this second idea pending"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-worker",
                        "--once",
                        "--run-now",
                        "--input",
                        str(chat),
                        "--min-chars",
                        "5",
                        "--extractor",
                        "rules",
                        "--batch-size",
                        "1",
                        "--vault",
                        str(vault),
                        "--graph",
                        str(graph),
                        "--min-note-atoms",
                        "1",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()
            notes = store.list_notes()
            graph_exists = graph.exists()
            vault_notes = list(vault.rglob("*.md"))

        self.assertEqual(code, 0)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertTrue(notes)
        self.assertTrue(graph_exists)
        self.assertTrue(vault_notes)
        self.assertIn("enqueued=2", out.getvalue())
        self.assertIn("notes=", out.getvalue())
        self.assertIn("vault_notes=", out.getvalue())

    def test_queue_build_can_feed_arcrift_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db)

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-build",
                        "--arcrift-db",
                        str(arcrift_db),
                        "--min-chars",
                        "5",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()

        self.assertEqual(code, 0)
        self.assertIn("Enqueued 2 fragments", out.getvalue())
        self.assertEqual(stats["pending"], 2)

    def test_queue_worker_can_auto_feed_arcrift_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            arcrift_db = Path(tmp) / "ArcRift.db"
            _create_arcrift_db(arcrift_db)

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-worker",
                        "--once",
                        "--run-now",
                        "--arcrift-db",
                        str(arcrift_db),
                        "--min-chars",
                        "5",
                        "--extractor",
                        "rules",
                        "--batch-size",
                        "1",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()
            atoms = store.list_atoms()

        self.assertEqual(code, 0)
        self.assertIn("enqueued=2", out.getvalue())
        self.assertEqual(len(atoms), 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["pending"], 1)

    def test_queue_build_can_feed_notes_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            inbox = Path(tmp) / "Inbox"
            inbox.mkdir()
            (inbox / "old-note.md").write_text(
                "# Old Product Note\n\nThis manually written note should enter the digestion queue.",
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-build",
                        "--notes-inbox",
                        str(inbox),
                        "--min-chars",
                        "20",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()

        self.assertEqual(code, 0)
        self.assertIn("Enqueued 1 fragments", out.getvalue())
        self.assertEqual(stats["pending"], 1)

    def test_queue_worker_can_auto_feed_notes_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            inbox = Path(tmp) / "Inbox"
            inbox.mkdir()
            (inbox / "old-note.md").write_text(
                "# Old Product Note\n\nThis manually written note should become an atom later.",
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "--db",
                        str(db),
                        "queue-worker",
                        "--once",
                        "--run-now",
                        "--notes-inbox",
                        str(inbox),
                        "--min-chars",
                        "20",
                        "--extractor",
                        "rules",
                        "--batch-size",
                        "1",
                    ]
                )
            store = MemoryStore(db)
            stats = store.queue_stats()
            atoms = store.list_atoms()

        self.assertEqual(code, 0)
        self.assertIn("enqueued=1", out.getvalue())
        self.assertEqual(len(atoms), 1)
        self.assertEqual(stats["done"], 1)

    def test_queue_errors_and_retry_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.enqueue_fragments(
                [
                    {
                        "id": "frag-error",
                        "source_file": "chat.jsonl",
                        "source": "chat.jsonl:line[1]",
                        "role": "user",
                        "text": "this fragment failed once",
                        "timestamp": None,
                    }
                ]
            )
            store.mark_queue_error("frag-error", "model timeout")

            out = io.StringIO()
            with redirect_stdout(out):
                errors_code = main(["--db", str(db), "queue-errors", "--limit", "5"])
            with redirect_stdout(out):
                retry_code = main(["--db", str(db), "queue-retry", "frag-error"])
            stats = store.queue_stats()

        self.assertEqual(errors_code, 0)
        self.assertEqual(retry_code, 0)
        self.assertIn("frag-error", out.getvalue())
        self.assertIn("model timeout", out.getvalue())
        self.assertIn("Requeued 1 error fragments", out.getvalue())
        self.assertEqual(stats.get("error", 0), 0)
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

    def test_inspire_feedback_command_accepts_latest_run_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite"
            store = MemoryStore(db)
            store.upsert_atoms(
                [
                    ThoughtAtom(
                        id="old",
                        source="sample.jsonl:line[1]",
                        role="user",
                        text="Older focus atom.",
                        summary="Older focus",
                        kind="idea",
                        tags=["old"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="focus",
                        source="sample.jsonl:line[2]",
                        role="user",
                        text="Current focus atom.",
                        summary="Current focus",
                        kind="idea",
                        tags=["focus"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.2,
                        metadata={},
                    ),
                    ThoughtAtom(
                        id="latent",
                        source="sample.jsonl:line[3]",
                        role="user",
                        text="Useful latent atom.",
                        summary="Useful latent",
                        kind="idea",
                        tags=["latent"],
                        timestamp=None,
                        importance=0.5,
                        activation=0.1,
                        metadata={},
                    ),
                ]
            )
            store.record_inspire_run(
                question="older question",
                focus_atom_ids=["old"],
                latent_atom_ids=["latent"],
                output_text="older",
            )
            latest_run_id = store.record_inspire_run(
                question="latest question",
                focus_atom_ids=["focus"],
                latent_atom_ids=["latent"],
                output_text="suggestion_id: 1\ncited_atom_ids: [focus, latent]",
            )
            store.record_inspire_suggestions(
                latest_run_id,
                [
                    {
                        "suggestion_id": "1",
                        "cited_atom_ids": ["focus", "latent"],
                        "text": "Use the latest bridge.",
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
                        "latest",
                        "--status",
                        "useful",
                        "--suggestion",
                        "1",
                    ]
                )
            edges = MemoryStore(db).list_edges()

        self.assertEqual(code, 0)
        self.assertIn(f"run={latest_run_id}", out.getvalue())
        self.assertEqual({edges[0].from_id, edges[0].to_id}, {"focus", "latent"})


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
                "cli-session",
                "CLI Trial",
                "chatgpt",
                "Synthetic CLI ArcRift session",
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
                "cli-session",
                "[User]: ArcRift saved this web chat for the digest queue.\n\n"
                "[Assistant]: The queue worker should process it later.",
                None,
                2,
                "chatgpt",
                "2026-06-26T00:00:00Z",
            ),
        )
        con.commit()


if __name__ == "__main__":
    unittest.main()
