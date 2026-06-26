from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SourceCandidate:
    label: str
    kind: str
    path: Path


SOURCE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("codex_history", "file", (".codex", "history.jsonl")),
    ("codex_sessions", "directory", (".codex", "sessions")),
    ("codex_archived_sessions", "directory", (".codex", "archived_sessions")),
    ("claude_history", "file", (".claude", "history.jsonl")),
    ("claude_projects", "directory", (".claude", "projects")),
    ("claude_sessions", "directory", (".claude", "sessions")),
)

ALLOWED_SUFFIXES = {".json", ".jsonl"}
SENSITIVE_NAME_PARTS = (
    "auth",
    "credential",
    "credentials",
    "gcp-oauth",
    "token",
    "secret",
    "setting",
    "settings",
    "config",
    "log",
    "cache",
)


def discover_sources(*, home: str | Path | None = None) -> list[SourceCandidate]:
    home_path = Path(home) if home is not None else Path.home()
    sources: list[SourceCandidate] = []
    for label, kind, parts in SOURCE_SPECS:
        path = home_path.joinpath(*parts)
        if path.exists():
            sources.append(SourceCandidate(label=label, kind=kind, path=path))
    return sources


def sources_for_labels(labels: Iterable[str], *, home: str | Path | None = None) -> list[SourceCandidate]:
    requested = {label.casefold() for label in labels}
    discovered = discover_sources(home=home)
    if not requested or "all" in requested:
        return discovered
    selected: list[SourceCandidate] = []
    for source in discovered:
        family = source.label.split("_", 1)[0]
        if source.label.casefold() in requested or family.casefold() in requested:
            selected.append(source)
    return selected


def expand_source_files(paths: Iterable[str | Path | SourceCandidate]) -> list[Path]:
    files: list[Path] = []
    for item in paths:
        path = item.path if isinstance(item, SourceCandidate) else Path(item)
        if path.is_file():
            if _is_allowed_file(path):
                files.append(path)
            continue
        if path.is_dir():
            files.extend(
                file
                for file in path.rglob("*")
                if file.is_file() and _is_allowed_file(file)
            )
    return sorted(dict.fromkeys(files), key=lambda file: str(file).casefold())


def _is_allowed_file(path: Path) -> bool:
    if path.suffix.casefold() not in ALLOWED_SUFFIXES:
        return False
    folded_parts = [part.casefold() for part in path.parts]
    return not any(
        sensitive in part
        for part in folded_parts
        for sensitive in SENSITIVE_NAME_PARTS
    )
