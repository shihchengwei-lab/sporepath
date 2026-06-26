from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .extractors import ExtractSignal, Extractor
from .ingest import _clean_text, _is_tool_noise, classify_kind, infer_tags, score_importance, summarize
from .models import ThoughtAtom


_TURN_MARKER = re.compile(r"(?m)^\[(User|Assistant)\]:\s*")


def parse_arcrift_raw_text(raw_text: str) -> list[dict[str, str]]:
    text = raw_text.strip()
    if not text:
        return []
    markers = list(_TURN_MARKER.finditer(text))
    if not markers:
        return [{"role": "unknown", "text": text}]

    turns: list[dict[str, str]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        body = text[marker.end() : end].strip()
        if not body:
            continue
        turns.append(
            {
                "role": marker.group(1).casefold(),
                "text": body,
            }
        )
    return turns


def extract_atoms_from_arcrift_db(
    path: str | Path,
    *,
    min_chars: int = 12,
    extractor: Extractor | None = None,
    max_turns: int | None = None,
    project: str | None = None,
) -> list[ThoughtAtom]:
    db_path = Path(path)
    if not db_path.exists():
        raise FileNotFoundError(f"ArcRift database not found: {db_path}")

    atoms: list[ThoughtAtom] = []
    for chat in _read_full_chats(db_path, project=project):
        for turn_index, turn in enumerate(parse_arcrift_raw_text(chat["rawText"])):
            if max_turns is not None and len(atoms) >= max_turns:
                return atoms
            text = _clean_text(turn["text"])
            if _is_tool_noise(text) or len(text) < min_chars:
                continue
            source = f"arcrift:{chat['sessionId']}:turn[{turn_index}]"
            metadata = {
                "source_file": str(db_path),
                "source_system": "arcrift",
                "arcrift_session_id": chat["sessionId"],
                "arcrift_project": chat["projectName"],
                "arcrift_platform": chat["platform"],
                "arcrift_message_count": chat["messageCount"],
            }
            atoms.append(
                _atom_from_arcrift_turn(
                    source=source,
                    role=turn["role"],
                    text=text,
                    timestamp=chat["timestamp"],
                    metadata=metadata,
                    extractor=extractor,
                )
            )
    return atoms


def _read_full_chats(path: Path, *, project: str | None) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        _assert_table_exists(con, "full_chats")
        rows = con.execute(
            """
            SELECT
                fc.sessionId,
                fc.rawText,
                fc.messageCount,
                fc.platform AS chatPlatform,
                fc.createdAt AS chatCreatedAt,
                s.projectName,
                s.platform AS sessionPlatform,
                s.createdAt AS sessionCreatedAt,
                s.updatedAt AS sessionUpdatedAt
            FROM full_chats fc
            LEFT JOIN sessions s ON s.id = fc.sessionId
            WHERE (? IS NULL OR s.projectName = ? OR fc.sessionId = ?)
            ORDER BY COALESCE(fc.createdAt, s.createdAt, s.updatedAt, fc.sessionId)
            """,
            (project, project, project),
        ).fetchall()

    return [
        {
            "sessionId": row["sessionId"],
            "rawText": row["rawText"],
            "messageCount": row["messageCount"] or 0,
            "platform": row["chatPlatform"] or row["sessionPlatform"] or "unknown",
            "projectName": row["projectName"] or row["sessionId"],
            "timestamp": row["chatCreatedAt"] or row["sessionCreatedAt"] or row["sessionUpdatedAt"],
        }
        for row in rows
    ]


def _assert_table_exists(con: sqlite3.Connection, table: str) -> None:
    row = con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if row is None:
        raise ValueError(f"not an ArcRift SQLite database: missing {table} table")


def _atom_from_arcrift_turn(
    *,
    source: str,
    role: str,
    text: str,
    timestamp: str | None,
    metadata: dict[str, Any],
    extractor: Extractor | None,
) -> ThoughtAtom:
    if extractor is not None:
        try:
            signal = extractor.extract(text, role=role)
        except Exception as exc:
            signal = ExtractSignal(
                keep=False,
                kind="note",
                summary="",
                tags=["extractor-error"],
                confidence=0.0,
                reason=str(exc),
            )
        if signal.keep:
            return _atom_from_signal(source, role, text, timestamp, metadata, signal)

    return _atom_from_rules(source, role, text, timestamp, metadata)


def _atom_from_rules(
    source: str,
    role: str,
    text: str,
    timestamp: str | None,
    metadata: dict[str, Any],
) -> ThoughtAtom:
    kind = classify_kind(text)
    tags = infer_tags(text)
    importance = score_importance(role, text, kind, tags)
    return ThoughtAtom(
        id=_atom_id(source, text),
        source=source,
        role=role,
        text=text,
        summary=summarize(text),
        kind=kind,
        tags=tags,
        timestamp=timestamp,
        importance=importance,
        activation=min(0.65, max(0.1, importance * 0.65)),
        metadata=metadata,
    )


def _atom_from_signal(
    source: str,
    role: str,
    text: str,
    timestamp: str | None,
    metadata: dict[str, Any],
    signal: ExtractSignal,
) -> ThoughtAtom:
    importance = round(min(0.95, max(0.05, 0.25 + signal.confidence * 0.55)), 3)
    return ThoughtAtom(
        id=_atom_id(source, text),
        source=source,
        role=role,
        text=text,
        summary=signal.handoff or signal.summary or summarize(text),
        kind=signal.kind,
        tags=signal.tags,
        timestamp=timestamp,
        importance=importance,
        activation=min(0.65, max(0.08, importance * 0.55)),
        metadata={
            **metadata,
            "extractor": "local-llm",
            "extractor_confidence": signal.confidence,
            "extractor_reason": signal.reason,
            "extractor_route": signal.route,
            "extractor_signals": signal.signals,
            "extractor_noise": signal.noise,
            "extractor_handoff": signal.handoff,
        },
    )


def _atom_id(source: str, text: str) -> str:
    return hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]
