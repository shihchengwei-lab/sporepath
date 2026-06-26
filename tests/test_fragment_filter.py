import unittest

from sporepath.fragment_filter import FragmentFilter, is_disposable_fragment


class FragmentFilterTests(unittest.TestCase):
    def test_rejects_command_xml_and_shell_transcript_noise(self):
        self.assertTrue(
            is_disposable_fragment(
                "<command-name>/remote-control</command-name> "
                "<command-message>remote-control</command-message> "
                "<command-args></command-args>"
            )
        )
        self.assertTrue(
            is_disposable_fragment(
                "kk789@SCACER:/mnt/e/project$ cat > .ccb/ccb.config <<'EOF' "
                "codex:codex; claude:claude EOF"
            )
        )
        self.assertTrue(
            is_disposable_fragment(
                "/remote-control is active · Continue here, on your phone, "
                "or at https://claude.ai/code/session_abc"
            )
        )

    def test_rejects_stale_recaps_but_keeps_actionable_pitch_context(self):
        self.assertTrue(
            is_disposable_fragment(
                "你要我比對本地 repo 和遠端，確認上個 agent 有沒有亂改。"
                "結果是完全一致，下一步等你決定要不要查 repo 以外設定。 "
                "(disable recaps in /config)"
            )
        )
        self.assertTrue(
            is_disposable_fragment(
                "在準備寄給 iThome 新聞部的材料；正在校稿一頁摘要。"
                "下一步：等你決定那句要保留還是降級。 (disable recaps in /config)"
            )
        )
        self.assertFalse(
            is_disposable_fragment(
                "You want to pitch your Claude Code teardown to 404 Media, "
                "and we're sharpening the news angle before writing the letter. "
                "Next: tell me whether to lead with the canary or Buddy. "
                "(disable recaps in /config)"
            )
        )

    def test_skips_near_duplicate_fragments_after_first_keep(self):
        gate = FragmentFilter(dedupe=True)

        first = gate.keep(
            "Add support for TSV input. We'll likely add more input formats "
            "(XML, YAML) later. Keep python3 -m pytest -q green."
        )
        second = gate.keep(
            "Add support for TSV input. We'll likely add more input formats "
            "(XML, YAML) later. Keep python3 -m pytest -q green."
        )

        self.assertTrue(first.keep)
        self.assertFalse(second.keep)
        self.assertEqual(second.reason, "near-duplicate")


if __name__ == "__main__":
    unittest.main()
