from __future__ import annotations

import json
import ntpath
import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from string import Template

from .automation import default_arcrift_db_path


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    input_path: Path | None
    arcrift_path: Path | None
    vault_path: Path
    graph_path: Path
    notes_inbox_path: Path | None = None


CONFIG_FILENAME = "config.json"
ENV_PATH_KEYS = ("USERPROFILE", "APPDATA", "LOCALAPPDATA")
CONFIG_FIELDS = ("db_path", "input_path", "arcrift_path", "vault_path", "graph_path", "notes_inbox_path")


def default_app_config(db_path: str | Path) -> AppConfig:
    home = Path.home()
    return AppConfig(
        db_path=Path(db_path),
        input_path=None,
        arcrift_path=default_arcrift_db_path(),
        vault_path=home / "Documents" / "Sporepath Vault",
        graph_path=Path("sporepath_graph.html"),
        notes_inbox_path=home / "Documents" / "Sporepath Inbox",
    )


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "Sporepath" / CONFIG_FILENAME


def make_portable_path(
    value: str | Path | None,
    *,
    base_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    if value is None or str(value).strip() == "":
        return ""
    text = str(value)
    if _is_windows_path(text):
        return _make_portable_windows_path(text, base_dir=base_dir, env=env)

    raw = Path(text)
    if not raw.is_absolute():
        return str(raw)

    env_values = env or os.environ
    resolved = raw.resolve(strict=False)
    for key in ENV_PATH_KEYS:
        root = env_values.get(key)
        if not root:
            continue
        relative = _relative_to(resolved, Path(root).resolve(strict=False))
        if relative is not None:
            return str(Path(f"%{key}%") / relative)

    if base_dir is not None:
        relative = _relative_to(resolved, Path(base_dir).resolve(strict=False))
        if relative is not None:
            return str(relative)

    return str(raw)


def expand_portable_path(
    value: str | Path | None,
    *,
    base_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    env_values = env or os.environ
    expanded = _expand_windows_vars(str(value), env_values)
    if _is_windows_path(expanded):
        return Path(ntpath.normpath(expanded))
    path = Path(os.path.expanduser(expanded))
    if path.is_absolute():
        return path
    if base_dir is not None and _is_windows_path(str(base_dir)):
        return Path(ntpath.normpath(ntpath.join(str(base_dir), str(PureWindowsPath(path)))))
    return (Path(base_dir) / path) if base_dir is not None else path


def load_app_config(
    default: AppConfig,
    *,
    config_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> AppConfig:
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    values: dict[str, Path | None] = {}
    for field in CONFIG_FIELDS:
        loaded = expand_portable_path(data.get(field), base_dir=base_dir, env=env)
        fallback = getattr(default, field)
        values[field] = loaded if loaded is not None else fallback
    return AppConfig(**values)


def save_app_config(
    config: AppConfig,
    *,
    config_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    path = Path(config_path) if config_path is not None else default_config_path()
    data = {
        field: make_portable_path(getattr(config, field), base_dir=base_dir, env=env)
        for field in CONFIG_FIELDS
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _make_portable_windows_path(
    value: str,
    *,
    base_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    env_values = env or os.environ
    for key in ENV_PATH_KEYS:
        root = env_values.get(key)
        if not root:
            continue
        relative = _windows_relative_to(value, root)
        if relative is not None:
            return f"%{key}%" if relative == "." else ntpath.join(f"%{key}%", relative)

    if base_dir is not None:
        relative = _windows_relative_to(value, str(base_dir))
        if relative is not None:
            return relative

    return ntpath.normpath(value)


def _windows_relative_to(path: str, root: str) -> str | None:
    normalized_path = ntpath.normcase(ntpath.normpath(path))
    normalized_root = ntpath.normcase(ntpath.normpath(root))
    try:
        common = ntpath.commonpath([normalized_path, normalized_root])
    except ValueError:
        return None
    if common != normalized_root:
        return None
    return ntpath.relpath(ntpath.normpath(path), ntpath.normpath(root))


def _is_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")


def _expand_windows_vars(value: str, env: dict[str, str]) -> str:
    expanded = value
    for key, replacement in env.items():
        expanded = expanded.replace(f"%{key}%", replacement)
    return Template(expanded).safe_substitute(env)
