import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_arcrift_chrome_launcher_loads_extension_profile(self):
        launcher = ROOT / "Launch-ArcRift-Chrome.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("Start-ArcRift.bat", text)
        self.assertIn("extension\\dist\\chrome", text)
        self.assertIn("%%~fI", text)
        self.assertIn("--load-extension=", text)
        self.assertIn("--user-data-dir=", text)
        self.assertIn("ArcRift Chrome Profile", text)

    def test_logged_in_chrome_launcher_uses_default_profile(self):
        launcher = ROOT / "Launch-ArcRift-Logged-In-Chrome.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("Start-ArcRift.bat", text)
        self.assertIn("extension\\dist\\chrome", text)
        self.assertIn("%%~fI", text)
        self.assertIn("Google\\Chrome\\User Data", text)
        self.assertIn("CHROME_PROFILE=Default", text)
        self.assertIn("--profile-directory=", text)
        self.assertIn("--load-extension=", text)
        self.assertIn("CloseMainWindow", text)
        self.assertIn("Stop-Process -Force", text)
        self.assertIn("https://chatgpt.com/", text)
        self.assertIn("https://claude.ai/", text)

    def test_sources_watcher_launcher_tracks_local_sources(self):
        launcher = ROOT / "Run-Sporepath-Sources-Watcher.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("watch-sources", text)
        self.assertIn("--source all", text)
        self.assertIn("Documents\\Sporepath Vault", text)
        self.assertIn("real_graph.html", text)

    def test_auto_launcher_starts_sources_watcher(self):
        launcher = ROOT / "Sporepath-Auto.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("Run-Sporepath-Sources-Watcher.bat", text)

    def test_queue_worker_launcher_runs_off_peak_scout(self):
        launcher = ROOT / "Run-Sporepath-Queue-Worker.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("queue-worker", text)
        self.assertIn("qwen3.5:4b", text)
        self.assertIn("--off-peak", text)
        self.assertIn("00:00-07:00", text)
        self.assertIn("--ollama-timeout-s", text)
        self.assertIn("--ollama-num-predict", text)
        self.assertIn("ollama list", text)

    def test_auto_launcher_starts_queue_worker(self):
        launcher = ROOT / "Sporepath-Auto.bat"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("Run-Sporepath-Queue-Worker.bat", text)


if __name__ == "__main__":
    unittest.main()
