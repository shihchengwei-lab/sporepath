from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import time
from pathlib import Path
from typing import Iterable

from .arcrift_import import _read_full_chats, parse_arcrift_raw_text
from .extractors import Extractor
from .fragment_filter import DEFAULT_DEDUPE_THRESHOLD, FragmentFilter
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


def is_off_peak_window(current: time, window: str) -> bool:
    start_text, end_text = _parse_window(window)
    start = _parse_hhmm(start_text)
    end = _parse_hhmm(end_text)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def collect_fragments_from_file(
    path: str | Path,
    *,
    min_chars: int = 12,
    max_turns: int | None = None,
    fragment_filter: FragmentFilter | None = None,
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
        if fragment_filter is not None and not fragment_filter.keep(text).keep:
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


def collect_fragments_from_arcrift_db(
    path: str | Path,
    *,
    min_chars: int = 12,
    max_turns: int | None = None,
    project: str | None = None,
    dedupe: bool = True,
    conservative: bool = True,
    dedupe_threshold: float = DEFAULT_DEDUPE_THRESHOLD,
    fragment_filter: FragmentFilter | None = None,
) -> list[dict[str, object]]:
    db_path = Path(path)
    if not db_path.exists():
        raise FileNotFoundError(f"ArcRift database not found: {db_path}")

    active_filter = fragment_filter or FragmentFilter(
        dedupe=dedupe,
        conservative=conservative,
        threshold=dedupe_threshold,
    )
    fragments: list[dict[str, object]] = []
    turns_read = 0
    for chat in _read_full_chats(db_path, project=project):
        for turn_index, turn in enumerate(parse_arcrift_raw_text(str(chat["rawText"] or ""))):
            if max_turns is not None and turns_read >= max_turns:
                return fragments
            turns_read += 1
            text = _clean_text(turn["text"])
            if _is_tool_noise(text) or len(text) < min_chars:
                continue
            if active_filter is not None and not active_filter.keep(text).keep:
                continue
            source = f"arcrift:{chat['sessionId']}:turn[{turn_index}]"
            fragment_id = hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]
            fragments.append(
                {
                    "id": fragment_id,
                    "source_file": str(db_path),
                    "source": source,
                    "role": turn.get("role", "unknown"),
                    "text": text,
                    "timestamp": chat.get("timestamp"),
                }
            )
    return fragments


def collect_fragments_from_files(
    paths: Iterable[str | Path],
    *,
    min_chars: int = 12,
    max_turns: int | None = None,
    dedupe: bool = True,
    conservative: bool = True,
    dedupe_threshold: float = DEFAULT_DEDUPE_THRESHOLD,
) -> list[dict[str, object]]:
    fragments: list[dict[str, object]] = []
    fragment_filter = FragmentFilter(
        dedupe=dedupe,
        conservative=conservative,
        threshold=dedupe_threshold,
    )
    for path in paths:
        fragments.extend(
            collect_fragments_from_file(
                path,
                min_chars=min_chars,
                max_turns=max_turns,
                fragment_filter=fragment_filter,
            )
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


def _parse_window(window: str) -> tuple[str, str]:
    parts = [part.strip() for part in window.split("-", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("off-peak window must look like HH:MM-HH:MM")
    return parts[0], parts[1]


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("off-peak time must use 00:00 through 23:59")
    return time(hour, minute)
