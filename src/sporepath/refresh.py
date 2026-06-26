from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .graph_export import export_graph_html
from .ingest import extract_atoms_from_file
from .notes import build_notes_from_atoms
from .source_discovery import expand_source_files
from .store import MemoryStore
from .vault_export import export_obsidian_vault


@dataclass(frozen=True)
class RefreshResult:
    atoms_imported: int
    atoms_after: int
    edges_rebuilt: int
    notes_built: int
    vault_notes_exported: int
    graph_path: Path | None


def refresh_memory(
    *,
    db_path: str | Path,
    input_path: str | Path | None = None,
    input_paths: Iterable[str | Path] | None = None,
    vault_path: str | Path | None = None,
    graph_path: str | Path | None = None,
    min_chars: int = 12,
    max_turns: int | None = None,
    min_note_atoms: int = 2,
    max_note_points: int = 5,
) -> RefreshResult:
    store = MemoryStore(db_path)
    imported = 0
    raw_inputs: list[str | Path] = []
    if input_path:
        raw_inputs.append(input_path)
    if input_paths:
        raw_inputs.extend(input_paths)
    for source_file in expand_source_files(raw_inputs):
        atoms = extract_atoms_from_file(source_file, min_chars=min_chars, max_turns=max_turns)
        imported += store.upsert_atoms(atoms)

    atoms_after = len(store.list_atoms())
    if atoms_after == 0:
        raise ValueError("memory database is empty; ingest chats before refresh")

    edges = store.rebuild_edges()
    notes = build_notes_from_atoms(
        store.list_atoms(),
        min_atoms=min_note_atoms,
        max_points=max_note_points,
    )
    notes_built = store.replace_notes(notes)

    vault_notes_exported = 0
    if vault_path is not None:
        vault_result = export_obsidian_vault(store, vault_path)
        vault_notes_exported = vault_result.notes_exported

    graph_written = None
    if graph_path is not None:
        graph_written = export_graph_html(store, graph_path)

    return RefreshResult(
        atoms_imported=imported,
        atoms_after=atoms_after,
        edges_rebuilt=edges,
        notes_built=notes_built,
        vault_notes_exported=vault_notes_exported,
        graph_path=graph_written,
    )
