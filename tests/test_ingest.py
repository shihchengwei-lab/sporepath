import json
import tempfile
import unittest
from pathlib import Path

from latent_brain.ingest import extract_atoms_from_file


class IngestTests(unittest.TestCase):
    def test_extracts_atoms_from_chatgpt_export(self):
        payload = [
            {
                "title": "Second brain idea",
                "mapping": {
                    "root": {
                        "id": "root",
                        "message": None,
                        "parent": None,
                        "children": ["m1"],
                    },
                    "m1": {
                        "id": "m1",
                        "message": {
                            "author": {"role": "user"},
                            "content": {
                                "content_type": "text",
                                "parts": [
                                    "我想做一個會沉睡的第二大腦，常用路徑加粗，不常用路徑沉到潛意識。"
                                ],
                            },
                            "create_time": 1782259200,
                        },
                        "parent": "root",
                        "children": ["m2"],
                    },
                    "m2": {
                        "id": "m2",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {
                                "content_type": "text",
                                "parts": [
                                    "最大風險是它會變成漂亮廢話，所以需要可驗證的靈感橋接。"
                                ],
                            },
                            "create_time": 1782259260,
                        },
                        "parent": "m1",
                        "children": [],
                    },
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conversations.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            atoms = extract_atoms_from_file(path)

        self.assertEqual(len(atoms), 2)
        self.assertEqual(atoms[0].role, "user")
        self.assertEqual(atoms[0].kind, "idea")
        self.assertIn("second-brain", atoms[0].tags)
        self.assertEqual(atoms[1].kind, "objection")
        self.assertIn("source_file", atoms[0].metadata)

    def test_extracts_atoms_from_jsonl(self):
        rows = [
            {
                "role": "user",
                "content": "PoC 應該先用規則整理 jsonl，不要一開始做完整 app。",
                "timestamp": "2026-06-24T12:00:00",
            },
            {
                "role": "assistant",
                "content": "可以，先把問題切成 thought atoms，再建立路徑權重。",
                "timestamp": "2026-06-24T12:00:15",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.jsonl"
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            atoms = extract_atoms_from_file(path)

        self.assertEqual([atom.role for atom in atoms], ["user", "assistant"])
        self.assertIn("poc", atoms[0].tags)
        self.assertGreater(atoms[0].importance, 0.0)

    def test_skips_tool_notifications_before_extractor(self):
        class FailingExtractor:
            def extract(self, _text, role="unknown"):
                raise AssertionError("tool noise should not be sent to extractor")

        row = {
            "role": "assistant",
            "content": "<task-notification><status>completed</status></task-notification>",
            "timestamp": "2026-06-24T12:00:00",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

            atoms = extract_atoms_from_file(path, extractor=FailingExtractor())

        self.assertEqual(atoms, [])

    def test_strips_system_reminder_from_user_text(self):
        row = {
            "role": "user",
            "content": "我想做一個真正會代謝的第二大腦。<system-reminder>Message sent at now.</system-reminder>",
            "timestamp": "2026-06-24T12:00:00",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

            atoms = extract_atoms_from_file(path)

        self.assertEqual(len(atoms), 1)
        self.assertNotIn("system-reminder", atoms[0].text)


if __name__ == "__main__":
    unittest.main()
