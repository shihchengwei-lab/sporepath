from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import DigestedNote
from .store import MemoryStore


@dataclass(frozen=True)
class VaultExportResult:
    path: Path
    notes_exported: int
    manifest_path: Path


@dataclass(frozen=True)
class VaultSyncResult:
    notes_touched: int
    atoms_touched: int


def export_obsidian_vault(store: MemoryStore, vault_path: str | Path) -> VaultExportResult:
    vault = Path(vault_path)
    notes = store.list_notes()
    if not notes:
        raise ValueError("no digested notes to export; run `sporepath digest` first")

    notes_dir = vault / "Digested Notes"
    meta_dir = vault / ".sporepath"
    notes_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    manifest_notes = []
    for note in notes:
        filename = _note_filename(note)
        note_path = notes_dir / filename
        note_path.write_text(_render_note_markdown(note), encoding="utf-8")
        stat = note_path.stat()
        manifest_notes.append(
            {
                "id": note.id,
                "title": note.title,
                "type": note.note_type,
                "activation": note.activation,
                "path": f"Digested Notes/{filename}",
                "source_atom_ids": note.source_atom_ids,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
        )

    manifest_path = meta_dir / "manifest.json"
    manifest = {
        "format": "sporepath-obsidian-vault",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "notes_exported": len(notes),
        "notes": manifest_notes,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return VaultExportResult(vault, len(notes), manifest_path)


def sync_obsidian_vault(
    store: MemoryStore,
    vault_path: str | Path,
    *,
    touch_amount: float = 0.15,
) -> VaultSyncResult:
    vault = Path(vault_path)
    manifest_path = vault / ".sporepath" / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("missing .sporepath/manifest.json; export the vault first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    touched_notes: list[str] = []
    touched_atoms: list[str] = []
    for entry in manifest.get("notes", []):
        note_path = vault / entry["path"]
        if not note_path.exists():
            continue
        stat = note_path.stat()
        if stat.st_mtime_ns == entry.get("mtime_ns") and stat.st_size == entry.get("size"):
            continue
        note_id = entry["id"]
        try:
            note = store.get_note(note_id)
        except KeyError:
            continue
        touched_notes.append(note_id)
        touched_atoms.extend(note.source_atom_ids)
    store.touch_notes(touched_notes, amount=touch_amount)
    unique_atoms = sorted(set(touched_atoms))
    store.touch_atoms(unique_atoms, amount=touch_amount)
    return VaultSyncResult(notes_touched=len(touched_notes), atoms_touched=len(unique_atoms))


def _render_note_markdown(note: DigestedNote) -> str:
    lines = [
        "---",
        f'sporepath_id: "{_yaml_escape(note.id)}"',
        f'type: "{_yaml_escape(note.note_type)}"',
        f'state: "{_activation_state(note.activation)}"',
        f"activation: {note.activation:.2f}",
        "tags:",
        *_yaml_list(note.tags),
        "source_atoms:",
        *_yaml_list(note.source_atom_ids),
        "source_spans:",
        *_yaml_list(note.source_spans),
        "---",
        "",
        f"# {note.title}",
        "",
        "## Summary",
        "",
        note.summary,
        "",
        "## Key Points",
        "",
        *_markdown_list(note.key_points),
    ]
    if note.open_questions:
        lines.extend(
            [
                "",
                "## Open Questions",
                "",
                *_markdown_list(note.open_questions),
            ]
        )
    lines.extend(
        [
            "",
            "## Sources",
            "",
            "### Source Atoms",
            "",
            *_markdown_code_list(note.source_atom_ids),
            "",
            "### Source Spans",
            "",
            *_markdown_code_list(note.source_spans),
            "",
        ]
    )
    return "\n".join(lines)


def _note_filename(note: DigestedNote) -> str:
    slug = _slugify(note.title)
    if not slug:
        slug = "digested-note"
    return f"{slug[:72].strip('-')}-{note.id[:7]}.md"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.casefold()).strip("-")
    return re.sub(r"-+", "-", slug)


def _activation_state(activation: float) -> str:
    if activation >= 0.65:
        return "focus"
    if activation <= 0.25:
        return "latent"
    return "active"


def _yaml_list(items: list[str]) -> list[str]:
    if not items:
        return ["  []"]
    return [f'  - "{_yaml_escape(item)}"' for item in items]


def _markdown_list(items: list[str]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- {item}" for item in items]


def _markdown_code_list(items: list[str]) -> list[str]:
    if not items:
        return ["- `(none)`"]
    return [f"- `{item}`" for item in items]


def _yaml_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
