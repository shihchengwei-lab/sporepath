import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sporepath.cli import main


class SporepathEntrypointTests(unittest.TestCase):
    def test_sporepath_module_exposes_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            db = Path(tmp) / "memory.sqlite"
            with redirect_stdout(out):
                code = main(["--db", str(db), "stats"])

        self.assertEqual(code, 0)
        self.assertIn("atoms=0", out.getvalue())


if __name__ == "__main__":
    unittest.main()
