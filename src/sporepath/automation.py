from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .arcrift_import import extract_atoms_from_arcrift_db
from .graph_export import export_graph_html
from .notes import build_notes_from_atoms
from .store import MemoryStore
from .vault_export import export_obsidian_vault


@dataclass(frozen=True)
class ArcRiftSyncResult:
    arcrift_db_path: Path
    atoms_imported: int
    atoms_after: int
    edges_rebuilt: int
    notes_built: int
    vault_notes_exported: int
    graph_path: Path | None


def default_arcrift_db_path(*, cwd: str | Path | None = None, home: str | Path | None = None) -> Path | None:
    base = Path(cwd) if cwd is not None else Path.cwd()
    user_home = Path(home) if home is not None else Path.home()
    candidates = [
        base.parent / "ArcRift" / "backend" / "ArcRift.db",
        user_home / "Desktop" / "GH_repos" / "ArcRift" / "backend" / "ArcRift.db",
        user_home / "ArcRift" / "backend" / "ArcRift.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def sync_arcrift_memory(
    *,
    db_path: str | Path,
    arcrift_db_path: str | Path | None = None,
    vault_path: str | Path | None = None,
    graph_path: str | Path | None = None,
    min_chars: int = 12,
    max_turns: int | None = None,
    min_note_atoms: int = 1,
    max_note_points: int = 5,
    project: str | None = None,
) -> ArcRiftSyncResult:
    detected = Path(arcrift_db_path) if arcrift_db_path else default_arcrift_db_path()
    if detected is None:
        raise ValueError("ArcRift.db not found; pass --arcrift-db or set up ArcRift first")

    store = MemoryStore(db_path)
    atoms = extract_atoms_from_arcrift_db(
        detected,
        min_chars=min_chars,
        max_turns=max_turns,
        project=project,
    )
    imported = store.upsert_atoms(atoms)
    atoms_after = len(store.list_atoms())

    edges = store.rebuild_edges() if atoms_after else 0
    notes_built = 0
    vault_notes_exported = 0
    if atoms_after:
        notes = build_notes_from_atoms(
            store.list_atoms(),
            min_atoms=min_note_atoms,
            max_points=max_note_points,
        )
        notes_built = store.replace_notes(notes)
        if vault_path is not None and notes:
            vault_result = export_obsidian_vault(store, vault_path)
            vault_notes_exported = vault_result.notes_exported

    graph_written = export_graph_html(store, graph_path) if graph_path is not None and atoms_after else None
    return ArcRiftSyncResult(
        arcrift_db_path=detected,
        atoms_imported=imported,
        atoms_after=atoms_after,
        edges_rebuilt=edges,
        notes_built=notes_built,
        vault_notes_exported=vault_notes_exported,
        graph_path=graph_written,
    )
