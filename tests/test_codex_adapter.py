import unittest

from sporepath.codex_adapter import build_inspiration_prompt
from sporepath.models import ThoughtAtom


class CodexAdapterTests(unittest.TestCase):
    def test_builds_prompt_with_focus_and_latent_candidates(self):
        focus = [
            ThoughtAtom(
                id="f1",
                source="chat:1",
                role="user",
                text="我正在做一個會代謝的第二大腦。",
                summary="會代謝的第二大腦",
                kind="idea",
                tags=["second-brain"],
                timestamp="2026-06-24T12:00:00",
                importance=0.8,
                activation=0.9,
                metadata={},
            )
        ]
        latent = [
            ThoughtAtom(
                id="l1",
                source="chat:old",
                role="user",
                text="神之一手可能來自平常不用的弱連結。",
                summary="神之一手來自弱連結",
                kind="analogy",
                tags=["go", "weak-link"],
                timestamp="2026-01-01T12:00:00",
                importance=0.8,
                activation=0.12,
                metadata={},
            )
        ]

        prompt = build_inspiration_prompt(
            question="PoC 要怎麼切才不會太大？",
            focus_atoms=focus,
            latent_atoms=latent,
        )

        self.assertIn("PoC 要怎麼切", prompt)
        self.assertIn("會代謝的第二大腦", prompt)
        self.assertIn("神之一手來自弱連結", prompt)
        self.assertIn("不要泛泛聯想", prompt)


if __name__ == "__main__":
    unittest.main()
