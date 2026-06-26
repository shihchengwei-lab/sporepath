from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .source_discovery import SourceCandidate, expand_source_files


SourcePath = str | Path | SourceCandidate


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class SourceSnapshot:
    files: dict[str, FileSignature]

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> "SourceSnapshot":
        signatures: dict[str, FileSignature] = {}
        for path in paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            signatures[str(path)] = FileSignature(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        return cls(files=signatures)


def build_source_snapshot(paths: Iterable[SourcePath]) -> SourceSnapshot:
    return SourceSnapshot.from_paths(expand_source_files(paths))


def source_snapshot_changed(previous: SourceSnapshot, paths: Iterable[SourcePath]) -> bool:
    current = build_source_snapshot(paths)
    return current.files != previous.files


def sqlite_watch_paths(path: str | Path) -> list[Path]:
    db_path = Path(path)
    return [
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ]
