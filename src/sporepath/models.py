from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ThoughtAtom:
    id: str
    source: str
    role: str
    text: str
    summary: str
    kind: str
    tags: list[str]
    timestamp: str | None
    importance: float
    activation: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DigestedNote:
    id: str
    title: str
    note_type: str
    summary: str
    key_points: list[str]
    open_questions: list[str]
    tags: list[str]
    source_atom_ids: list[str]
    source_spans: list[str]
    activation: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    relation: str
    weight: float
    last_used: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
