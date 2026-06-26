from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable

from .models import DigestedNote, ThoughtAtom


NOTE_TYPE_KINDS = {
    "decision_note": {"decision", "question"},
    "friction_note": {"objection", "bug", "friction"},
}

STRUCTURE_TAGS = {"friction", "bug", "state-machine", "debug"}


def build_notes_from_atoms(
    atoms: Iterable[ThoughtAtom],
    *,
    min_atoms: int = 2,
    max_points: int = 5,
) -> list[DigestedNote]:
    grouped: dict[str, list[ThoughtAtom]] = defaultdict(list)
    for atom in atoms:
        anchor = _anchor_tag(atom)
        grouped[anchor].append(atom)

    notes: list[DigestedNote] = []
    for anchor, group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda atom: (-atom.activation, -atom.importance, atom.id))
        if len(ordered) < min_atoms:
            continue
        note_type = _note_type_for_group(ordered)
        notes.append(_build_note(note_type, anchor, ordered, max_points=max_points))
    return sorted(notes, key=lambda note: (-note.activation, note.title))


def _build_note(
    note_type: str,
    anchor: str,
    atoms: list[ThoughtAtom],
    *,
    max_points: int,
) -> DigestedNote:
    key_points = _unique(atom.summary for atom in atoms)[:max_points]
    open_questions = _unique(atom.summary for atom in atoms if atom.kind == "question")[:max_points]
    source_atom_ids = [atom.id for atom in atoms]
    source_spans = _unique(atom.source for atom in atoms)
    tags = sorted({tag for atom in atoms for tag in atom.tags})
    activation = round(sum(atom.activation for atom in atoms) / len(atoms), 3)
    note_id = _note_id(note_type, anchor, source_atom_ids)
    title = f"{_note_type_title(note_type)}: {anchor}"
    summary = _summary_sentence(key_points, open_questions)
    return DigestedNote(
        id=note_id,
        title=title,
        note_type=note_type,
        summary=summary,
        key_points=key_points,
        open_questions=open_questions,
        tags=tags,
        source_atom_ids=source_atom_ids,
        source_spans=source_spans,
        activation=activation,
        metadata={"builder": "rules", "anchor": anchor},
    )


def _note_type(atom: ThoughtAtom) -> str:
    if atom.kind in NOTE_TYPE_KINDS["friction_note"] or set(atom.tags).intersection(STRUCTURE_TAGS):
        return "friction_note"
    if atom.kind in NOTE_TYPE_KINDS["decision_note"]:
        return "decision_note"
    return "concept_note"


def _note_type_for_group(atoms: list[ThoughtAtom]) -> str:
    types = [_note_type(atom) for atom in atoms]
    if "friction_note" in types:
        return "friction_note"
    if any(note_type == "concept_note" for note_type in types):
        return "concept_note"
    return "decision_note"


def _anchor_tag(atom: ThoughtAtom) -> str:
    for tag in atom.tags:
        if tag != "uncategorized":
            return tag
    return atom.kind


def _note_type_title(note_type: str) -> str:
    return {
        "concept_note": "Concept note",
        "decision_note": "Decision note",
        "friction_note": "Friction note",
    }.get(note_type, "Digested note")


def _summary_sentence(key_points: list[str], open_questions: list[str]) -> str:
    if not key_points:
        return "No stable summary yet."
    summary = "; ".join(key_points[:3])
    if open_questions:
        summary += f" Open question: {open_questions[0]}"
    return summary


def _note_id(note_type: str, anchor: str, atom_ids: list[str]) -> str:
    basis = "\n".join([note_type, anchor, *atom_ids])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
