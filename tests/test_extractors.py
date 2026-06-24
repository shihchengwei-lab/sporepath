import json
import tempfile
import unittest
from pathlib import Path

from latent_brain.extractors import ExtractSignal, OllamaExtractor, parse_signal_json
from latent_brain.ingest import extract_atoms_from_file


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

    def test_ollama_extractor_uses_transport_response(self):
        def fake_transport(_payload):
            self.assertFalse(_payload["think"])
            return json.dumps(
                {
                    "keep": True,
                    "kind": "taste",
                    "summary": "文案不要太文言",
                    "tags": ["writing", "player-facing"],
                    "confidence": 0.91,
                    "reason": "這是可重用偏好",
                },
                ensure_ascii=False,
            )

        extractor = OllamaExtractor(model="qwen3:1.7b", transport=fake_transport)
        signal = extractor.extract("太文言，產品介紹不是寫成給玩家的話嗎？")

        self.assertEqual(signal.kind, "taste")
        self.assertEqual(signal.summary, "文案不要太文言")
        self.assertIn("player-facing", signal.tags)

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
        self.assertEqual(atoms[0].summary, "用使用訊號剪枝")
        self.assertIn("slime-mold", atoms[0].tags)
        self.assertEqual(atoms[0].metadata["extractor_confidence"], 0.88)


if __name__ == "__main__":
    unittest.main()
