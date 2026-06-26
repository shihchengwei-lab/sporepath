from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import DigestedNote, Edge, ThoughtAtom


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

    def latent_candidates(self, question: str, *, limit: int = 12, active_ceiling: float = 0.45) -> list[ThoughtAtom]:
        atoms = self.list_atoms()
        latent = [atom for atom in atoms if atom.activation <= active_ceiling]
        pool = latent or atoms
        reliable = sorted(
            pool,
            key=lambda atom: self._reliable_latent_score(question, atom),
            reverse=True,
        )
        weird = sorted(
            pool,
            key=lambda atom: self._weird_bridge_score(question, atom),
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
            con.execute("DELETE FROM edges")
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
