import json
import tempfile
import unittest
from pathlib import Path

from sporepath.extractors import (
    ExtractSignal,
    OllamaExtractor,
    build_extraction_prompt,
    is_degenerate_model_output,
    parse_signal_json,
)
from sporepath.ingest import extract_atoms_from_file


class ExtractorTests(unittest.TestCase):
    def test_parse_signal_json_accepts_fenced_json(self):
        raw = """```json
        {
          "keep": true,
          "kind": "framework",
          "summary": "分辨產品摩擦與目標族群不符",
          "tags": ["product-judgment", "friction"],
          "confidence": 0.82,
          "reason": "可重用判斷框架"
        }
        ```"""

        signal = parse_signal_json(raw)

        self.assertTrue(signal.keep)
        self.assertEqual(signal.kind, "framework")
        self.assertEqual(signal.tags, ["product-judgment", "friction"])
        self.assertGreater(signal.confidence, 0.8)

    def test_parse_signal_json_accepts_prefixed_json_with_trailing_text(self):
        raw = """
        Here is the JSON:
        {
          "keep": true,
          "route": "product",
          "kind": "decision",
          "summary": "Keep the product judgment.",
          "signals": ["product judgment"],
          "noise": [],
          "handoff": "Use this when evaluating the same product tradeoff.",
          "tags": ["product"],
          "confidence": 0.81,
          "reason": "reusable"
        }
        Extra explanation that should be ignored.
        """

        signal = parse_signal_json(raw)

        self.assertTrue(signal.keep)
        self.assertEqual(signal.route, "product")
        self.assertEqual(signal.summary, "Keep the product judgment.")

    def test_parse_signal_json_uses_first_complete_json_object(self):
        raw = """{"keep": true, "kind": "idea", "summary": "first", "tags": ["one"], "confidence": 0.8}
        {"keep": false, "kind": "note", "summary": "second", "tags": ["two"], "confidence": 0.1}
        """

        signal = parse_signal_json(raw)

        self.assertTrue(signal.keep)
        self.assertEqual(signal.summary, "first")
        self.assertEqual(signal.tags, ["one"])

    def test_ollama_extractor_uses_transport_response(self):
        def fake_transport(_payload):
            self.assertFalse(_payload["think"])
            self.assertEqual(_payload["options"]["num_predict"], 320)
            return json.dumps(
                {
                    "keep": True,
                    "kind": "taste",
                    "route": "preference",
                    "summary": "文案不要太文言",
                    "signals": ["玩家語氣", "不要太文言"],
                    "noise": ["抱怨語氣"],
                    "handoff": "玩家-facing 文案要白話，不要文言腔。",
                    "tags": ["writing", "player-facing"],
                    "confidence": 0.91,
                    "reason": "這是可重用偏好",
                },
                ensure_ascii=False,
            )

        extractor = OllamaExtractor(model="qwen3:1.7b", num_predict=320, transport=fake_transport)
        signal = extractor.extract("太文言，產品介紹不是寫成給玩家的話嗎？")

        self.assertEqual(signal.kind, "taste")
        self.assertEqual(signal.summary, "文案不要太文言")
        self.assertEqual(signal.route, "preference")
        self.assertIn("玩家語氣", signal.signals)
        self.assertIn("抱怨語氣", signal.noise)
        self.assertEqual(signal.handoff, "玩家-facing 文案要白話，不要文言腔。")
        self.assertIn("player-facing", signal.tags)

    def test_ollama_extractor_canary_rejects_degenerate_output(self):
        extractor = OllamaExtractor(model="qwen3.5:4b", transport=lambda _payload: "000000000000000000")

        result = extractor.check_canary()

        self.assertFalse(result.ok)
        self.assertIn("degenerate", result.reason)

    def test_degenerate_model_output_detects_repeated_zeroes(self):
        self.assertTrue(is_degenerate_model_output("000000000000000000"))
        self.assertFalse(is_degenerate_model_output('{"keep": false}'))

    def test_parse_signal_json_accepts_scout_fields(self):
        raw = json.dumps(
            {
                "keep": True,
                "route": "debug",
                "kind": "bug_memory",
                "summary": "restore 狀態沒有同步",
                "signals": ["restore flow", "ownership state"],
                "noise": ["我快瘋了"],
                "handoff": "購買 restore 後要檢查本地 ownership 狀態是否回寫。",
                "tags": ["purchase", "state-sync"],
                "confidence": 0.86,
                "reason": "可重複踩到的 debug 記憶",
            },
            ensure_ascii=False,
        )

        signal = parse_signal_json(raw)

        self.assertTrue(signal.keep)
        self.assertEqual(signal.route, "debug")
        self.assertEqual(signal.kind, "bug_memory")
        self.assertEqual(signal.signals, ["restore flow", "ownership state"])
        self.assertEqual(signal.noise, ["我快瘋了"])
        self.assertEqual(signal.handoff, "購買 restore 後要檢查本地 ownership 狀態是否回寫。")

    def test_parse_signal_json_filters_placeholder_noise(self):
        raw = json.dumps(
            {
                "keep": True,
                "route": "idea",
                "kind": "idea",
                "summary": "模型透明度與安全護欄",
                "signals": ["透明度", "安全護欄"],
                "noise": ["該丟掉的字：該丟掉的字", "寒暄、工具噪音、一次性進度", "無", "我快瘋了"],
                "handoff": "評估模型公司宣傳與安全護欄落差時可用。",
                "tags": ["ai-safety", "transparency"],
                "confidence": 0.8,
                "reason": "可重用判斷",
            },
            ensure_ascii=False,
        )

        signal = parse_signal_json(raw)

        self.assertEqual(signal.noise, ["我快瘋了"])

    def test_extraction_prompt_keeps_fragment_explicit_for_small_models(self):
        prompt = build_extraction_prompt(
            "我在做一個第二大腦工具，想測試小模型能不能整理聊天。",
            role="user",
        )

        self.assertIn("fragment_text:", prompt)
        self.assertIn("我在做一個第二大腦工具", prompt)
        self.assertIn("Output exactly one JSON object", prompt)
        self.assertIn("summary must name the concrete subject", prompt)
        self.assertIn("noise must list only exact disposable words", prompt)
        self.assertIn("handoff must explain when this memory would help", prompt)
        self.assertLess(prompt.find("fragment_text:"), prompt.find("Output exactly one JSON object"))
        self.assertNotIn("<<<", prompt)

    def test_ingest_can_use_custom_extractor(self):
        class FakeExtractor:
            def extract(self, _text, role="unknown"):
                return ExtractSignal(
                    keep=True,
                    kind="framework",
                    summary="用使用訊號剪枝",
                    tags=["mvp", "slime-mold"],
                    confidence=0.88,
                    reason="可重用架構判斷",
                    route="decision",
                    signals=["使用訊號", "剪枝"],
                    noise=["口語填充"],
                    handoff="用使用訊號決定哪些路徑加粗或沉入封存。",
                )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "role": "user",
                        "content": "小模型負責探路，後續剪枝看使用訊號。",
                        "timestamp": "2026-06-24T12:00:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            atoms = extract_atoms_from_file(path, extractor=FakeExtractor())

        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0].kind, "framework")
        self.assertEqual(atoms[0].summary, "用使用訊號決定哪些路徑加粗或沉入封存。")
        self.assertIn("slime-mold", atoms[0].tags)
        self.assertEqual(atoms[0].metadata["extractor_confidence"], 0.88)
        self.assertEqual(atoms[0].metadata["extractor_route"], "decision")
        self.assertEqual(atoms[0].metadata["extractor_signals"], ["使用訊號", "剪枝"])
        self.assertEqual(atoms[0].metadata["extractor_noise"], ["口語填充"])
        self.assertEqual(atoms[0].metadata["extractor_handoff"], "用使用訊號決定哪些路徑加粗或沉入封存。")


if __name__ == "__main__":
    unittest.main()
