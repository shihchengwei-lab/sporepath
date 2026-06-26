import unittest

from sporepath.codex_adapter import build_inspiration_prompt, parse_inspiration_suggestions
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
        self.assertIn("Do not summarize the notes", prompt)
        self.assertIn("Use this exact block format", prompt)

    def test_prompt_includes_scout_metadata_and_feedback_fields(self):
        latent = [
            ThoughtAtom(
                id="l2",
                source="chat:debug",
                role="user",
                text="Restore purchase state can drift after restart.",
                summary="Purchase restore state drift",
                kind="bug_memory",
                tags=["purchase", "state"],
                timestamp=None,
                importance=0.6,
                activation=0.1,
                metadata={
                    "extractor_route": "debug",
                    "extractor_signals": ["restore", "ownership"],
                    "extractor_noise": ["angry filler"],
                    "extractor_handoff": "Check local ownership cache before UI state.",
                },
            )
        ]

        prompt = build_inspiration_prompt(
            question="How should I validate this memory tool?",
            focus_atoms=[],
            latent_atoms=latent,
        )

        self.assertIn("route=debug", prompt)
        self.assertIn("signals=[restore, ownership]", prompt)
        self.assertIn("handoff=Check local ownership cache before UI state.", prompt)
        self.assertIn("noise=[angry filler]", prompt)
        self.assertIn("suggestion_id", prompt)
        self.assertIn("cited_atom_ids", prompt)
        self.assertIn("next_step:", prompt)
        self.assertIn("validation:", prompt)

    def test_parse_inspiration_suggestions_reads_cited_atoms(self):
        output = """
suggestion_id: 1
cited_atom_ids: [focus, latent]
next_move: Use an endgame test.

suggestion_id: 2
cited_atom_ids: unrelated
next_move: Try a second bridge.
"""

        suggestions = parse_inspiration_suggestions(
            output,
            known_atom_ids={"focus", "latent", "unrelated"},
        )

        self.assertEqual(
            suggestions,
            [
                {
                    "suggestion_id": "1",
                    "cited_atom_ids": ["focus", "latent"],
                    "text": "suggestion_id: 1\ncited_atom_ids: [focus, latent]\nnext_move: Use an endgame test.",
                },
                {
                    "suggestion_id": "2",
                    "cited_atom_ids": ["unrelated"],
                    "text": "suggestion_id: 2\ncited_atom_ids: unrelated\nnext_move: Try a second bridge.",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
