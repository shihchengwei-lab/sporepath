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
class Edge:
    from_id: str
    to_id: str
    relation: str
    weight: float
    last_used: str | None = None
