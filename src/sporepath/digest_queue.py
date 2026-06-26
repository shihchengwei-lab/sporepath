from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from .extractors import Extractor
from .ingest import (
    _atom_from_signal,
    _atom_from_turn,
    _clean_text,
    _is_tool_noise,
    _read_turns,
)
from .store import MemoryStore


@dataclass(frozen=True)
class DigestQueueResult:
    processed: int
    atoms_created: int
    skipped: int
    errors: int


def collect_fragments_from_file(
    path: str | Path,
    *,
    min_chars: int = 12,
    max_turns: int | None = None,
) -> list[dict[str, object]]:
    path = Path(path)
    fragments: list[dict[str, object]] = []
    turns_read = 0
    for turn in _read_turns(path):
        if max_turns is not None and turns_read >= max_turns:
            break
        turns_read += 1
        text = _clean_text(turn["text"])
        if _is_tool_noise(text) or len(text) < min_chars:
            continue
        source = turn.get("source") or f"{path.name}:turn[{turns_read - 1}]"
        role = turn.get("role", "unknown")
        fragment_id = hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]
        fragments.append(
            {
                "id": fragment_id,
                "source_file": str(path),
                "source": source,
                "role": role,
                "text": text,
                "timestamp": turn.get("timestamp"),
            }
        )
    return fragments


def collect_fragments_from_files(
    paths: Iterable[str | Path],
    *,
    min_chars: int = 12,
    max_turns: int | None = None,
) -> list[dict[str, object]]:
    fragments: list[dict[str, object]] = []
    for path in paths:
        fragments.extend(
            collect_fragments_from_file(path, min_chars=min_chars, max_turns=max_turns)
        )
    return fragments


def process_digest_queue(
    store: MemoryStore,
    *,
    extractor: Extractor | None = None,
    limit: int = 10,
) -> DigestQueueResult:
    processed = 0
    atoms_created = 0
    skipped = 0
    errors = 0

    for fragment in store.next_queue_fragments(limit=limit):
        processed += 1
        try:
            atom = _atom_from_fragment(fragment, extractor=extractor)
        except _SkipFragment as exc:
            store.mark_queue_skipped(fragment["id"], str(exc))
            skipped += 1
            continue
        except Exception as exc:
            store.mark_queue_error(fragment["id"], str(exc))
            errors += 1
            continue

        store.upsert_atoms([atom])
        store.mark_queue_done(fragment["id"], atom.id)
        atoms_created += 1

    return DigestQueueResult(
        processed=processed,
        atoms_created=atoms_created,
        skipped=skipped,
        errors=errors,
    )


def _atom_from_fragment(fragment: dict[str, object], *, extractor: Extractor | None):
    path = Path(str(fragment["source_file"]))
    source = str(fragment["source"])
    role = str(fragment["role"])
    text = str(fragment["text"])
    timestamp = fragment.get("timestamp")
    timestamp_value = str(timestamp) if timestamp is not None else None

    if extractor is None:
        atom = _atom_from_turn(path, source, role, text, timestamp_value)
    else:
        signal = extractor.extract(text, role=role)
        if not signal.keep:
            raise _SkipFragment(signal.reason or "extractor returned keep=false")
        atom = _atom_from_signal(path, source, role, text, timestamp_value, signal)

    metadata = {
        **atom.metadata,
        "queue_id": fragment["id"],
        "queue_status": "done",
    }
    return replace(atom, metadata=metadata)


class _SkipFragment(Exception):
    pass
