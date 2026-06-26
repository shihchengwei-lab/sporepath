import io
import json
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main
from sporepath.evaluation import build_extraction_eval, score_eval_sheet


class EvaluationTests(unittest.TestCase):
    def test_build_extraction_eval_writes_jsonl_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            out = Path(tmp) / "eval.jsonl"
            report = Path(tmp) / "eval.md"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "role": "user",
                                "content": "Debug 卡住：購買狀態重開後又顯示可購買，可能是 restore 流程沒回寫本地狀態。",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "role": "assistant",
                                "content": "<tool-use id='noise'></tool-use>",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            result = build_extraction_eval(
                input_paths=[chat],
                out_path=out,
                report_path=report,
                limit=5,
            )

            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result.cases_written, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["role"], "user")
            self.assertIn("prediction", rows[0])
            self.assertIn("human", rows[0])
            self.assertIn("route", rows[0]["prediction"])
            self.assertIn("signals", rows[0]["prediction"])
            self.assertIn("handoff", rows[0]["prediction"])
            self.assertIn("signal_found", rows[0]["human"])
            self.assertIn("handoff_sufficient", rows[0]["human"])
            self.assertIn("Debug 卡住", report_text)

    def test_build_extraction_eval_can_filter_by_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            out = Path(tmp) / "eval.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "role": "user",
                                "content": "普通產品想法：這段不該進 debug eval。",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "role": "user",
                                "content": "Debug 記憶：controller disposed 之後還呼叫 setState。",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            result = build_extraction_eval(
                input_paths=[chat],
                out_path=out,
                contains=["controller disposed"],
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result.cases_written, 1)
        self.assertIn("controller disposed", rows[0]["text"])

    def test_build_extraction_eval_skips_overlong_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            out = Path(tmp) / "eval.jsonl"
            chat.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "role": "user",
                                "content": "bug " + ("too long " * 80),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "role": "user",
                                "content": "bug 短片段：restore 狀態沒有同步。",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            result = build_extraction_eval(
                input_paths=[chat],
                out_path=out,
                contains=["bug"],
                min_chars=1,
                max_chars=80,
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result.cases_written, 1)
        self.assertIn("restore", rows[0]["text"])

    def test_build_extraction_eval_can_limit_cases_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.jsonl"
            second = root / "b.jsonl"
            out = root / "eval.jsonl"
            first.write_text(
                "\n".join(
                    json.dumps({"role": "user", "content": f"first reusable memory {index}"})
                    for index in range(4)
                ),
                encoding="utf-8",
            )
            second.write_text(
                "\n".join(
                    json.dumps({"role": "user", "content": f"second reusable memory {index}"})
                    for index in range(4)
                ),
                encoding="utf-8",
            )

            result = build_extraction_eval(
                input_paths=[root],
                out_path=out,
                limit=4,
                min_chars=5,
                per_file_limit=2,
            )
            records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            counts = Counter(Path(record["source_file"]).name for record in records)

        self.assertEqual(result.cases_written, 4)
        self.assertEqual(counts["a.jsonl"], 2)
        self.assertEqual(counts["b.jsonl"], 2)

    def test_build_extraction_eval_can_dedupe_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.jsonl"
            second = root / "b.jsonl"
            out = root / "eval.jsonl"
            duplicate = "Add support for TSV input. Keep python3 -m pytest -q green."
            first.write_text(
                json.dumps({"role": "user", "content": duplicate}),
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

            result = build_extraction_eval(
                input_paths=[root],
                out_path=out,
                limit=3,
                min_chars=5,
                dedupe=True,
            )
            records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result.cases_written, 2)
        self.assertEqual([record["text"] for record in records].count(duplicate), 1)

    def test_build_extraction_eval_accepts_checkpoint_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            out = Path(tmp) / "eval.jsonl"
            report = Path(tmp) / "eval.md"
            chat.write_text(
                "\n".join(
                    json.dumps({"role": "user", "content": f"checkpoint reusable memory {index}"})
                    for index in range(3)
                ),
                encoding="utf-8",
            )

            result = build_extraction_eval(
                input_paths=[chat],
                out_path=out,
                report_path=report,
                limit=3,
                min_chars=5,
                checkpoint_every=1,
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            report_exists = report.exists()

        self.assertEqual(result.cases_written, 3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(report_exists)

    def test_score_eval_sheet_summarizes_human_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            rows = [
                {
                    "id": "good",
                    "prediction": {"keep": True, "route": "debug"},
                    "human": {
                        "keep": True,
                        "route": "debug",
                        "signal_found": True,
                        "noise_marked": True,
                        "handoff_sufficient": True,
                        "useful": True,
                    },
                },
                {
                    "id": "bad",
                    "prediction": {"keep": True, "route": "idea"},
                    "human": {
                        "keep": False,
                        "route": "debug",
                        "signal_found": False,
                        "noise_marked": False,
                        "handoff_sufficient": False,
                        "useful": False,
                    },
                },
            ]
            sheet.write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )

            result = score_eval_sheet(sheet)

        self.assertEqual(result.total_cases, 2)
        self.assertEqual(result.scored_cases, 2)
        self.assertAlmostEqual(result.pass_rate, 0.5)
        self.assertAlmostEqual(result.keep_agreement, 0.5)
        self.assertAlmostEqual(result.route_agreement, 0.5)
        self.assertAlmostEqual(result.signal_found_rate, 0.5)
        self.assertAlmostEqual(result.noise_marked_rate, 0.5)
        self.assertAlmostEqual(result.handoff_sufficient_rate, 0.5)

    def test_score_eval_sheet_still_accepts_legacy_note_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "legacy_eval.jsonl"
            sheet.write_text(
                json.dumps(
                    {
                        "id": "legacy",
                        "prediction": {"keep": True},
                        "human": {
                            "keep": True,
                            "summary_quality": 4,
                            "structure_quality": 4,
                            "noise": False,
                            "useful": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = score_eval_sheet(sheet)

        self.assertEqual(result.scored_cases, 1)
        self.assertAlmostEqual(result.pass_rate, 1.0)
        self.assertAlmostEqual(result.avg_summary_quality, 4.0)
        self.assertAlmostEqual(result.avg_structure_quality, 4.0)

    def test_eval_extract_cli_writes_review_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "chat.jsonl"
            out = Path(tmp) / "eval.jsonl"
            report = Path(tmp) / "eval.md"
            chat.write_text(
                json.dumps(
                    {
                        "role": "user",
                        "content": "產品判斷：不要為擴張 TA 改掉核心玩法，要先分辨摩擦和族群不符。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--db",
                        str(Path(tmp) / "memory.sqlite"),
                        "eval-extract",
                        "--input",
                        str(chat),
                        "--out",
                        str(out),
                        "--report",
                        str(report),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertTrue(report.exists())
            self.assertIn("Eval cases", stdout.getvalue())

    def test_eval_score_cli_prints_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "eval.jsonl"
            sheet.write_text(
                json.dumps(
                    {
                        "id": "case",
                        "prediction": {"keep": True, "route": "debug"},
                        "human": {
                            "keep": True,
                            "route": "debug",
                            "signal_found": True,
                            "noise_marked": True,
                            "handoff_sufficient": True,
                            "useful": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--db", str(Path(tmp) / "memory.sqlite"), "eval-score", str(sheet)])

        self.assertEqual(code, 0)
        self.assertIn("scored=1/1", stdout.getvalue())
        self.assertIn("pass_rate=100.0%", stdout.getvalue())
        self.assertIn("signal_found=100.0%", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
