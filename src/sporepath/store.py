from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import DigestedNote, Edge, ThoughtAtom


POSITIVE_INSPIRE_STATUSES = {
    "selected": 0.14,
    "useful": 0.18,
    "applied": 0.28,
}
VALID_INSPIRE_STATUSES = set(POSITIVE_INSPIRE_STATUSES) | {"boring", "wrong", "ignored"}


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert_atoms(self, atoms: Iterable[ThoughtAtom]) -> int:
        rows = list(atoms)
        with closing(self._connect()) as con:
            con.executemany(
                """
                INSERT INTO atoms (
                    id, source, role, text, summary, kind, tags, timestamp,
                    importance, activation, metadata, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    role = excluded.role,
                    text = excluded.text,
                    summary = excluded.summary,
                    kind = excluded.kind,
                    tags = excluded.tags,
                    timestamp = excluded.timestamp,
                    importance = excluded.importance,
                    activation = max(atoms.activation, excluded.activation),
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                [self._atom_row(atom) for atom in rows],
            )
            con.commit()
        return len(rows)

    def get_atom(self, atom_id: str) -> ThoughtAtom:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM atoms WHERE id = ?", (atom_id,)).fetchone()
        if row is None:
            raise KeyError(atom_id)
        return self._row_to_atom(row)

    def upsert_notes(self, notes: Iterable[DigestedNote]) -> int:
        rows = list(notes)
        with closing(self._connect()) as con:
            con.executemany(
                """
                INSERT INTO notes (
                    id, title, note_type, summary, key_points, open_questions,
                    tags, source_atom_ids, source_spans, activation, metadata,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    note_type = excluded.note_type,
                    summary = excluded.summary,
                    key_points = excluded.key_points,
                    open_questions = excluded.open_questions,
                    tags = excluded.tags,
                    source_atom_ids = excluded.source_atom_ids,
                    source_spans = excluded.source_spans,
                    activation = max(notes.activation, excluded.activation),
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                [self._note_row(note) for note in rows],
            )
            con.commit()
        return len(rows)

    def replace_notes(self, notes: Iterable[DigestedNote]) -> int:
        rows = list(notes)
        with closing(self._connect()) as con:
            con.execute("DELETE FROM notes")
            con.executemany(
                """
                INSERT INTO notes (
                    id, title, note_type, summary, key_points, open_questions,
                    tags, source_atom_ids, source_spans, activation, metadata,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._note_row(note) for note in rows],
            )
            con.commit()
        return len(rows)

    def get_note(self, note_id: str) -> DigestedNote:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise KeyError(note_id)
        return self._row_to_note(row)

    def list_notes(self, *, limit: int | None = None) -> list[DigestedNote]:
        sql = """
            SELECT * FROM notes
            ORDER BY activation DESC, updated_at DESC, title ASC
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with closing(self._connect()) as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_note(row) for row in rows]

    def list_atoms(self) -> list[ThoughtAtom]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM atoms").fetchall()
        return [self._row_to_atom(row) for row in rows]

    def list_edges(self) -> list[Edge]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT from_id, to_id, relation, weight, last_used, evidence, confidence FROM edges"
            ).fetchall()
        return [
            Edge(
                from_id=row["from_id"],
                to_id=row["to_id"],
                relation=row["relation"],
                weight=row["weight"],
                last_used=row["last_used"],
                evidence=json.loads(row["evidence"]),
                confidence=row["confidence"],
            )
            for row in rows
        ]

    def focus_atoms(self, *, limit: int = 8) -> list[ThoughtAtom]:
        with closing(self._connect()) as con:
            rows = con.execute(
                """
                SELECT * FROM atoms
                ORDER BY activation DESC, importance DESC, COALESCE(timestamp, '') DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_atom(row) for row in rows]

    def latent_candidates(
        self,
        question: str,
        *,
        limit: int = 12,
        active_ceiling: float = 0.45,
        focus_atom_ids: Iterable[str] | None = None,
    ) -> list[ThoughtAtom]:
        focus_ids = set(focus_atom_ids or [])
        atoms = self.list_atoms()
        latent = [atom for atom in atoms if atom.activation <= active_ceiling and atom.id not in focus_ids]
        pool = latent or [atom for atom in atoms if atom.id not in focus_ids] or atoms
        bridge_boosts = self._inspire_feedback_boosts(focus_ids)
        reliable = sorted(
            pool,
            key=lambda atom: self._reliable_latent_score(question, atom) + bridge_boosts.get(atom.id, 0.0),
            reverse=True,
        )
        weird = sorted(
            pool,
            key=lambda atom: self._weird_bridge_score(question, atom) + bridge_boosts.get(atom.id, 0.0),
            reverse=True,
        )
        return _interleave_unique([reliable, weird], limit=limit)

    def touch_atoms(self, atom_ids: Iterable[str], *, amount: float = 0.2) -> None:
        ids = list(atom_ids)
        if not ids:
            return
        now = _now()
        with closing(self._connect()) as con:
            con.executemany(
                "UPDATE atoms SET activation = min(1.0, activation + ?), updated_at = ? WHERE id = ?",
                [(amount, now, atom_id) for atom_id in ids],
            )
            con.commit()

    def touch_notes(self, note_ids: Iterable[str], *, amount: float = 0.2) -> None:
        ids = list(note_ids)
        if not ids:
            return
        now = _now()
        with closing(self._connect()) as con:
            con.executemany(
                "UPDATE notes SET activation = min(1.0, activation + ?), updated_at = ? WHERE id = ?",
                [(amount, now, note_id) for note_id in ids],
            )
            con.commit()

    def enqueue_fragments(self, fragments: Iterable[dict[str, object]]) -> int:
        rows = []
        now = _now()
        for fragment in fragments:
            rows.append(
                (
                    str(fragment["id"]),
                    str(fragment["source_file"]),
                    str(fragment["source"]),
                    str(fragment.get("role", "unknown")),
                    str(fragment["text"]),
                    fragment.get("timestamp"),
                    "pending",
                    0,
                    "",
                    None,
                    now,
                    now,
                )
            )
        if not rows:
            return 0
        with closing(self._connect()) as con:
            before = con.total_changes
            con.executemany(
                """
                INSERT OR IGNORE INTO digest_queue (
                    id, source_file, source, role, text, timestamp,
                    status, attempts, last_error, atom_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = con.total_changes - before
            con.commit()
        return inserted

    def queue_stats(self) -> dict[str, int]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT status, COUNT(*) AS count FROM digest_queue GROUP BY status"
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def next_queue_fragments(self, *, limit: int = 10) -> list[dict[str, object]]:
        with closing(self._connect()) as con:
            rows = con.execute(
                """
                SELECT id, source_file, source, role, text, timestamp, attempts
                FROM digest_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "source_file": row["source_file"],
                "source": row["source"],
                "role": row["role"],
                "text": row["text"],
                "timestamp": row["timestamp"],
                "attempts": row["attempts"],
            }
            for row in rows
        ]

    def queue_errors(self, *, limit: int = 20) -> list[dict[str, object]]:
        with closing(self._connect()) as con:
            rows = con.execute(
                """
                SELECT id, source_file, source, role, text, timestamp, attempts, last_error, updated_at
                FROM digest_queue
                WHERE status = 'error'
                ORDER BY updated_at DESC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "source_file": row["source_file"],
                "source": row["source"],
                "role": row["role"],
                "text": row["text"],
                "timestamp": row["timestamp"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def reset_queue_errors(self, ids: Iterable[str] | None = None) -> int:
        id_list = list(ids or [])
        now = _now()
        with closing(self._connect()) as con:
            before = con.total_changes
            if id_list:
                placeholders = ", ".join("?" for _ in id_list)
                con.execute(
                    f"""
                    UPDATE digest_queue
                    SET status = 'pending', last_error = '', updated_at = ?
                    WHERE status = 'error' AND id IN ({placeholders})
                    """,
                    (now, *id_list),
                )
            else:
                con.execute(
                    """
                    UPDATE digest_queue
                    SET status = 'pending', last_error = '', updated_at = ?
                    WHERE status = 'error'
                    """,
                    (now,),
                )
            changed = con.total_changes - before
            con.commit()
        return changed

    def mark_queue_done(self, fragment_id: str, atom_id: str) -> None:
        self._mark_queue_status(fragment_id, "done", atom_id=atom_id)

    def mark_queue_skipped(self, fragment_id: str, reason: str = "") -> None:
        self._mark_queue_status(fragment_id, "skipped", error=reason)

    def mark_queue_error(self, fragment_id: str, error: str) -> None:
        self._mark_queue_status(fragment_id, "error", error=error)

    def record_inspire_run(
        self,
        *,
        question: str,
        focus_atom_ids: Iterable[str],
        latent_atom_ids: Iterable[str],
        output_text: str = "",
    ) -> str:
        run_id = uuid.uuid4().hex[:16]
        now = _now()
        with closing(self._connect()) as con:
            con.execute(
                """
                INSERT INTO inspire_runs (
                    id, question, focus_atom_ids, latent_atom_ids, output_text,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    question,
                    json.dumps(list(focus_atom_ids), ensure_ascii=False),
                    json.dumps(list(latent_atom_ids), ensure_ascii=False),
                    output_text,
                    now,
                    now,
                ),
            )
            con.commit()
        self.record_usage_event(
            "inspire_run",
            target_type="inspire_run",
            target_id=run_id,
            metadata={"question": question},
        )
        return run_id

    def record_usage_event(
        self,
        event: str,
        *,
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex[:16]
        with closing(self._connect()) as con:
            con.execute(
                """
                INSERT INTO usage_events (
                    id, event, target_type, target_id, metadata, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event,
                    target_type,
                    target_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            con.commit()
        return event_id

    def usage_event_counts(self) -> dict[str, int]:
        with closing(self._connect()) as con:
            rows = con.execute(
                """
                SELECT event, COUNT(*) AS count
                FROM usage_events
                GROUP BY event
                ORDER BY event
                """
            ).fetchall()
        return {str(row["event"]): int(row["count"]) for row in rows}

    def latest_inspire_run_id(self) -> str | None:
        with closing(self._connect()) as con:
            row = con.execute(
                """
                SELECT id
                FROM inspire_runs
                ORDER BY datetime(created_at) DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["id"]) if row is not None else None

    def record_inspire_suggestions(self, run_id: str, suggestions: Iterable[dict[str, object]]) -> int:
        rows = []
        for suggestion in suggestions:
            suggestion_id = str(suggestion.get("suggestion_id", "")).strip()
            cited_atom_ids = [str(atom_id) for atom_id in suggestion.get("cited_atom_ids", [])]
            if not suggestion_id or not cited_atom_ids:
                continue
            rows.append(
                (
                    run_id,
                    suggestion_id,
                    str(suggestion.get("text", "")),
                    json.dumps(cited_atom_ids, ensure_ascii=False),
                    _now(),
                )
            )
        if not rows:
            return 0
        with closing(self._connect()) as con:
            run = con.execute("SELECT id FROM inspire_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            con.executemany(
                """
                INSERT INTO inspire_suggestions (
                    run_id, suggestion_id, text, cited_atom_ids, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, suggestion_id) DO UPDATE SET
                    text = excluded.text,
                    cited_atom_ids = excluded.cited_atom_ids
                """,
                rows,
            )
            con.commit()
        return len(rows)

    def get_inspire_suggestion(self, run_id: str, suggestion_id: str) -> dict[str, object]:
        with closing(self._connect()) as con:
            row = con.execute(
                """
                SELECT run_id, suggestion_id, text, cited_atom_ids
                FROM inspire_suggestions
                WHERE run_id = ? AND suggestion_id = ?
                """,
                (run_id, suggestion_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"{run_id}:{suggestion_id}")
        return {
            "run_id": row["run_id"],
            "suggestion_id": row["suggestion_id"],
            "text": row["text"],
            "cited_atom_ids": json.loads(row["cited_atom_ids"]),
        }

    def apply_inspire_feedback(
        self,
        run_id: str,
        *,
        atom_ids: Iterable[str] | None = None,
        suggestion_id: str | None = None,
        status: str,
        note: str = "",
        amount: float | None = None,
    ) -> dict[str, int]:
        normalized_status = status.strip().casefold()
        if normalized_status not in VALID_INSPIRE_STATUSES:
            raise ValueError(f"unsupported inspire feedback status: {status}")

        suggestion_atom_ids: list[str] = []
        normalized_suggestion_id = suggestion_id.strip() if suggestion_id else None
        if normalized_suggestion_id:
            suggestion = self.get_inspire_suggestion(run_id, normalized_suggestion_id)
            suggestion_atom_ids = [str(atom_id) for atom_id in suggestion["cited_atom_ids"]]

        ids = sorted(dict.fromkeys([*(atom_ids or []), *suggestion_atom_ids]))
        if not ids:
            raise ValueError("inspire feedback requires at least one atom id or suggestion id")

        with closing(self._connect()) as con:
            run = con.execute("SELECT id FROM inspire_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            missing = [
                atom_id
                for atom_id in ids
                if con.execute("SELECT id FROM atoms WHERE id = ?", (atom_id,)).fetchone() is None
            ]
            if missing:
                raise KeyError(", ".join(missing))

        feedback_amount = (
            amount
            if amount is not None
            else POSITIVE_INSPIRE_STATUSES.get(normalized_status, 0.0)
        )
        now = _now()
        feedback_id = uuid.uuid4().hex[:16]
        bridges = _pairs(ids) if normalized_status in POSITIVE_INSPIRE_STATUSES else []

        with closing(self._connect()) as con:
            con.execute(
                """
                INSERT INTO inspire_feedback (
                    id, run_id, status, atom_ids, note, amount, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    run_id,
                    normalized_status,
                    json.dumps(ids, ensure_ascii=False),
                    note,
                    feedback_amount,
                    now,
                ),
            )
            if normalized_status in POSITIVE_INSPIRE_STATUSES and feedback_amount > 0:
                con.executemany(
                    "UPDATE atoms SET activation = min(1.0, activation + ?), updated_at = ? WHERE id = ?",
                    [(feedback_amount, now, atom_id) for atom_id in ids],
                )
                for left, right in bridges:
                    evidence = {
                        "type": "inspire_feedback",
                        "run_id": run_id,
                        "feedback_id": feedback_id,
                        "status": normalized_status,
                        "atom_ids": [left, right],
                        "note": note,
                    }
                    if normalized_suggestion_id:
                        evidence["suggestion_id"] = normalized_suggestion_id
                    con.execute(
                        """
                        INSERT INTO edges (
                            from_id, to_id, relation, weight, last_used, evidence, confidence
                        )
                        VALUES (?, ?, 'inspire_feedback', ?, ?, ?, ?)
                        ON CONFLICT(from_id, to_id, relation) DO UPDATE SET
                            weight = min(1.0, edges.weight + excluded.weight),
                            last_used = excluded.last_used,
                            evidence = excluded.evidence,
                            confidence = min(0.95, edges.confidence + excluded.confidence * 0.25)
                        """,
                        (
                            left,
                            right,
                            min(1.0, feedback_amount),
                            now,
                            json.dumps(evidence, ensure_ascii=False),
                            round(min(0.95, 0.55 + feedback_amount), 3),
                        ),
                    )
            con.execute("UPDATE inspire_runs SET updated_at = ? WHERE id = ?", (now, run_id))
            con.commit()
        self.record_usage_event(
            "inspire_feedback",
            target_type="inspire_run",
            target_id=run_id,
            metadata={
                "status": normalized_status,
                "atom_ids": ids,
                "suggestion_id": normalized_suggestion_id or "",
                "bridges_strengthened": len(bridges),
            },
        )
        return {
            "atoms_touched": len(ids) if normalized_status in POSITIVE_INSPIRE_STATUSES else 0,
            "bridges_strengthened": len(bridges),
        }

    def decay_all(self, *, factor: float = 0.92, floor: float = 0.05) -> int:
        with closing(self._connect()) as con:
            con.execute(
                "UPDATE atoms SET activation = max(?, activation * ?), updated_at = ?",
                (floor, factor, _now()),
            )
            atom_changes = con.execute("SELECT changes()").fetchone()[0]
            con.execute(
                "UPDATE notes SET activation = max(?, activation * ?), updated_at = ?",
                (floor, factor, _now()),
            )
            note_changes = con.execute("SELECT changes()").fetchone()[0]
            con.commit()
            return atom_changes + note_changes

    def rebuild_edges(self, *, min_shared_tags: int = 1) -> int:
        atoms = self.list_atoms()
        edges: list[Edge] = []
        for index, left in enumerate(atoms):
            left_tags = set(left.tags)
            for right in atoms[index + 1 :]:
                shared = left_tags.intersection(right.tags)
                if len(shared) < min_shared_tags or shared == {"uncategorized"}:
                    continue
                weight = min(1.0, len(shared) / math.sqrt(max(len(left_tags), 1) * max(len(right.tags), 1)))
                relation = "shared_tags:" + ",".join(sorted(shared))
                confidence = round(min(0.95, 0.45 + weight * 0.4), 3)
                evidence = {
                    "type": "shared_tags",
                    "shared_tags": sorted(shared),
                    "left_tags": sorted(left_tags),
                    "right_tags": sorted(right.tags),
                }
                edges.append(
                    Edge(
                        left.id,
                        right.id,
                        relation,
                        round(weight, 3),
                        _now(),
                        evidence,
                        confidence,
                    )
                )

        with closing(self._connect()) as con:
            con.execute("DELETE FROM edges WHERE relation LIKE 'shared_tags:%'")
            con.executemany(
                """
                INSERT INTO edges (from_id, to_id, relation, weight, last_used, evidence, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.from_id,
                        edge.to_id,
                        edge.relation,
                        edge.weight,
                        edge.last_used,
                        json.dumps(edge.evidence, ensure_ascii=False),
                        edge.confidence,
                    )
                    for edge in edges
                ],
            )
            con.commit()
        return len(edges)

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as con:
            atoms = con.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]
            edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        return {"atoms": atoms, "edges": edges, "notes": notes}

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS atoms (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    timestamp TEXT,
                    importance REAL NOT NULL,
                    activation REAL NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL,
                    last_used TEXT,
                    evidence TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    PRIMARY KEY (from_id, to_id, relation)
                )
                """
            )
            self._ensure_column(con, "edges", "evidence", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(con, "edges", "confidence", "REAL NOT NULL DEFAULT 1.0")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    note_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    key_points TEXT NOT NULL,
                    open_questions TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    source_atom_ids TEXT NOT NULL,
                    source_spans TEXT NOT NULL,
                    activation REAL NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS inspire_runs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    focus_atom_ids TEXT NOT NULL,
                    latent_atom_ids TEXT NOT NULL,
                    output_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS inspire_feedback (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    atom_ids TEXT NOT NULL,
                    note TEXT NOT NULL,
                    amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS inspire_suggestions (
                    run_id TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    cited_atom_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, suggestion_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS digest_queue (
                    id TEXT PRIMARY KEY,
                    source_file TEXT NOT NULL,
                    source TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    atom_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.commit()

    def _ensure_column(self, con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _atom_row(self, atom: ThoughtAtom) -> tuple:
        now = _now()
        return (
            atom.id,
            atom.source,
            atom.role,
            atom.text,
            atom.summary,
            atom.kind,
            json.dumps(atom.tags, ensure_ascii=False),
            atom.timestamp,
            atom.importance,
            atom.activation,
            json.dumps(atom.metadata, ensure_ascii=False),
            now,
            now,
        )

    def _row_to_atom(self, row: sqlite3.Row) -> ThoughtAtom:
        return ThoughtAtom(
            id=row["id"],
            source=row["source"],
            role=row["role"],
            text=row["text"],
            summary=row["summary"],
            kind=row["kind"],
            tags=json.loads(row["tags"]),
            timestamp=row["timestamp"],
            importance=row["importance"],
            activation=row["activation"],
            metadata=json.loads(row["metadata"]),
        )

    def _note_row(self, note: DigestedNote) -> tuple:
        now = _now()
        return (
            note.id,
            note.title,
            note.note_type,
            note.summary,
            json.dumps(note.key_points, ensure_ascii=False),
            json.dumps(note.open_questions, ensure_ascii=False),
            json.dumps(note.tags, ensure_ascii=False),
            json.dumps(note.source_atom_ids, ensure_ascii=False),
            json.dumps(note.source_spans, ensure_ascii=False),
            note.activation,
            json.dumps(note.metadata, ensure_ascii=False),
            now,
            now,
        )

    def _row_to_note(self, row: sqlite3.Row) -> DigestedNote:
        return DigestedNote(
            id=row["id"],
            title=row["title"],
            note_type=row["note_type"],
            summary=row["summary"],
            key_points=json.loads(row["key_points"]),
            open_questions=json.loads(row["open_questions"]),
            tags=json.loads(row["tags"]),
            source_atom_ids=json.loads(row["source_atom_ids"]),
            source_spans=json.loads(row["source_spans"]),
            activation=row["activation"],
            metadata=json.loads(row["metadata"]),
        )

    def _mark_queue_status(
        self,
        fragment_id: str,
        status: str,
        *,
        atom_id: str | None = None,
        error: str = "",
    ) -> None:
        with closing(self._connect()) as con:
            con.execute(
                """
                UPDATE digest_queue
                SET status = ?,
                    attempts = attempts + 1,
                    last_error = ?,
                    atom_id = COALESCE(?, atom_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (status, error, atom_id, _now(), fragment_id),
            )
            con.commit()

    def _reliable_latent_score(self, question: str, atom: ThoughtAtom) -> float:
        question_folded = question.casefold()
        overlap = sum(1 for tag in atom.tags if tag.casefold() in question_folded)
        novelty = 1.0 - min(1.0, atom.activation)
        return (atom.importance * 0.55) + (novelty * 0.35) + (overlap * 0.1)

    def _weird_bridge_score(self, question: str, atom: ThoughtAtom) -> float:
        novelty = 1.0 - min(1.0, atom.activation)
        bridge = max(_tag_overlap(question, atom), _text_overlap(question, atom))
        low_importance_bonus = 1.0 - min(1.0, atom.importance)
        return (novelty * 0.55) + (bridge * 0.3) + (low_importance_bonus * 0.15)

    def _inspire_feedback_boosts(self, focus_atom_ids: Iterable[str]) -> dict[str, float]:
        focus_ids = sorted(dict.fromkeys(focus_atom_ids))
        if not focus_ids:
            return {}
        placeholders = ", ".join("?" for _ in focus_ids)
        with closing(self._connect()) as con:
            rows = con.execute(
                f"""
                SELECT from_id, to_id, weight
                FROM edges
                WHERE relation = 'inspire_feedback'
                  AND (from_id IN ({placeholders}) OR to_id IN ({placeholders}))
                """,
                [*focus_ids, *focus_ids],
            ).fetchall()
        boosts: dict[str, float] = {}
        focus_set = set(focus_ids)
        for row in rows:
            other_id = row["to_id"] if row["from_id"] in focus_set else row["from_id"]
            if other_id in focus_set:
                continue
            boosts[other_id] = max(boosts.get(other_id, 0.0), min(1.0, row["weight"]) * 1.2)
        return boosts


def _interleave_unique(pools: list[list[ThoughtAtom]], *, limit: int) -> list[ThoughtAtom]:
    result: list[ThoughtAtom] = []
    seen: set[str] = set()
    index = 0
    while len(result) < limit:
        added = False
        for pool in pools:
            if index >= len(pool):
                continue
            atom = pool[index]
            if atom.id in seen:
                continue
            seen.add(atom.id)
            result.append(atom)
            added = True
            if len(result) >= limit:
                break
        if not added and all(index >= len(pool) - 1 for pool in pools):
            break
        index += 1
    return result


def _pairs(ids: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            pairs.append((left, right) if left <= right else (right, left))
    return pairs


def _tag_overlap(question: str, atom: ThoughtAtom) -> float:
    folded = question.casefold()
    return 1.0 if any(tag.casefold() in folded for tag in atom.tags) else 0.0


def _text_overlap(question: str, atom: ThoughtAtom) -> float:
    question_tokens = set(_tokens(question))
    if not question_tokens:
        return 0.0
    atom_tokens = set(_tokens(f"{atom.summary} {atom.text}"))
    if not atom_tokens:
        return 0.0
    return len(question_tokens.intersection(atom_tokens)) / len(question_tokens)


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9]{3,}", text.casefold()) if token]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
