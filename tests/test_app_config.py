import json
import tempfile
import unittest
from pathlib import Path

from sporepath.app_config import (
    AppConfig,
    expand_portable_path,
    load_app_config,
    make_portable_path,
    save_app_config,
)


class AppConfigPersistenceTests(unittest.TestCase):
    def test_portable_path_uses_userprofile_instead_of_absolute_user_path(self):
        env = {"USERPROFILE": r"C:\Users\alice"}

        stored = make_portable_path(
            r"C:\Users\alice\Documents\Sporepath Vault",
            env=env,
        )
        expanded = expand_portable_path(
            stored,
            env={"USERPROFILE": r"D:\Users\bob"},
        )

        self.assertEqual(stored, r"%USERPROFILE%\Documents\Sporepath Vault")
        self.assertEqual(expanded, Path(r"D:\Users\bob\Documents\Sporepath Vault"))

    def test_relative_paths_stay_relative_to_the_checkout(self):
        stored = make_portable_path("real_memory.sqlite", base_dir=Path(r"C:\repo"))
        expanded = expand_portable_path(stored, base_dir=Path(r"D:\other-repo"))

        self.assertEqual(stored, "real_memory.sqlite")
        self.assertEqual(expanded, Path(r"D:\other-repo\real_memory.sqlite"))

    def test_config_round_trip_uses_portable_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            base = Path(tmp) / "repo"
            config = AppConfig(
                db_path=base / "real_memory.sqlite",
                input_path=None,
                arcrift_path=Path(r"C:\Users\alice\Desktop\GH_repos\ArcRift\backend\ArcRift.db"),
                vault_path=Path(r"C:\Users\alice\Documents\Sporepath Vault"),
                graph_path=base / "sporepath_graph.html",
                notes_inbox_path=Path(r"C:\Users\alice\Documents\Sporepath Inbox"),
            )

            save_app_config(
                config,
                config_path=config_path,
                base_dir=base,
                env={"USERPROFILE": r"C:\Users\alice"},
            )
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            loaded = load_app_config(
                AppConfig(
                    db_path=Path("fallback.sqlite"),
                    input_path=None,
                    arcrift_path=None,
                    vault_path=Path("fallback-vault"),
                    graph_path=Path("fallback.html"),
                    notes_inbox_path=Path("fallback-inbox"),
                ),
                config_path=config_path,
                base_dir=Path(r"D:\other-repo"),
                env={"USERPROFILE": r"D:\Users\bob"},
            )

        self.assertEqual(raw["db_path"], "real_memory.sqlite")
        self.assertEqual(raw["vault_path"], r"%USERPROFILE%\Documents\Sporepath Vault")
        self.assertEqual(raw["notes_inbox_path"], r"%USERPROFILE%\Documents\Sporepath Inbox")
        self.assertEqual(loaded.db_path, Path(r"D:\other-repo\real_memory.sqlite"))
        self.assertEqual(loaded.vault_path, Path(r"D:\Users\bob\Documents\Sporepath Vault"))
        self.assertEqual(loaded.notes_inbox_path, Path(r"D:\Users\bob\Documents\Sporepath Inbox"))


if __name__ == "__main__":
    unittest.main()
