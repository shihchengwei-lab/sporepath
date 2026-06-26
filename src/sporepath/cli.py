from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .app_config import default_app_config
from .codex_adapter import build_inspiration_prompt, codex_command, run_codex_exec
from .extractors import OllamaExtractor
from .graph_export import export_graph_html
from .ingest import extract_atoms_from_file
from .notes import build_notes_from_atoms
from .refresh import refresh_memory
from .source_discovery import discover_sources, sources_for_labels
from .store import MemoryStore
from .vault_export import export_obsidian_vault


DEFAULT_DB = Path("memory.sqlite")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sporepath")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite memory database path.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the local memory database.")

    ingest = sub.add_parser("ingest", help="Import ChatGPT/Claude/Codex JSON or JSONL.")
    ingest.add_argument("path")
    ingest.add_argument("--min-chars", type=int, default=12)
    ingest.add_argument("--max-turns", type=int, default=None, help="Only read the first N turns; useful for MVP trials.")
    ingest.add_argument("--extractor", choices=["rules", "ollama"], default="rules")
    ingest.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model for --extractor ollama.")
    ingest.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    ingest.add_argument("--min-confidence", type=float, default=0.55)

    focus = sub.add_parser("focus", help="Show currently thick focus paths.")
    focus.add_argument("--limit", type=int, default=8)

    show = sub.add_parser("show", help="Show one thought atom by id.")
    show.add_argument("id")

    digest = sub.add_parser("digest", help="Build readable notes from thought atoms.")
    digest.add_argument("--min-atoms", type=int, default=2)
    digest.add_argument("--max-points", type=int, default=5)

    notes = sub.add_parser("notes", help="List readable digested notes.")
    notes.add_argument("--limit", type=int, default=12)

    show_note = sub.add_parser("show-note", help="Show one digested note by id.")
    show_note.add_argument("id")

    export_vault = sub.add_parser("export-vault", help="Export digested notes as an Obsidian Markdown vault.")
    export_vault.add_argument("path")

    refresh = sub.add_parser("refresh", help="Run ingest, digest, vault export, and graph export in one step.")
    refresh.add_argument("--input", default=None, help="Optional chat export path to ingest before refreshing.")
    refresh.add_argument("--source", action="append", default=[], help="Auto-detected source family or label: all, codex, claude, codex_history, claude_projects, etc.")
    refresh.add_argument("--home", default=None, help="Override home directory for source detection.")
    refresh.add_argument("--vault", default=None, help="Optional Obsidian vault output path.")
    refresh.add_argument("--graph", default=None, help="Optional graph HTML output path.")
    refresh.add_argument("--min-chars", type=int, default=12)
    refresh.add_argument("--max-turns", type=int, default=None)
    refresh.add_argument("--min-note-atoms", type=int, default=2)
    refresh.add_argument("--max-note-points", type=int, default=5)

    app = sub.add_parser("app", help="Open the small Sporepath desktop window.")
    app.add_argument("--dry-run", action="store_true", help="Print the app defaults without opening a window.")

    sources = sub.add_parser("sources", help="List allowlisted Codex/Claude conversation sources.")
    sources.add_argument("--home", default=None, help="Override home directory for source detection.")

    graph = sub.add_parser("graph", help="Export an interactive local HTML graph.")
    graph.add_argument("--out", default="graph.html")
    graph.add_argument("--limit", type=int, default=160)

    decay = sub.add_parser("decay", help="Fade every path a little.")
    decay.add_argument("--factor", type=float, default=0.92)
    decay.add_argument("--floor", type=float, default=0.05)

    touch = sub.add_parser("touch", help="Strengthen one or more atom ids.")
    touch.add_argument("ids", nargs="+")
    touch.add_argument("--amount", type=float, default=0.2)

    inspire = sub.add_parser("inspire", help="Ask Codex for weird-but-bridged latent ideas.")
    inspire.add_argument("question")
    inspire.add_argument("--focus-limit", type=int, default=6)
    inspire.add_argument("--latent-limit", type=int, default=12)
    inspire.add_argument("--dry-run", action="store_true", help="Print the Codex prompt without running Codex.")
    inspire.add_argument("--timeout-s", type=int, default=300)

    sub.add_parser("stats", help="Show database counts.")
    sub.add_parser("doctor", help="Check local CLI assumptions.")

    args = parser.parse_args(argv)
    store = MemoryStore(args.db)

    if args.command == "init":
        print(f"Initialized {Path(args.db).resolve()}")
        return 0

    if args.command == "ingest":
        extractor = None
        if args.extractor == "ollama":
            extractor = OllamaExtractor(
                model=args.model,
                host=args.ollama_host,
                min_confidence=args.min_confidence,
            )
        atoms = extract_atoms_from_file(
            args.path,
            min_chars=args.min_chars,
            extractor=extractor,
            max_turns=args.max_turns,
        )
        inserted = store.upsert_atoms(atoms)
        edges = store.rebuild_edges()
        print(
            f"Imported {inserted} thought atoms with extractor={args.extractor}; "
            f"rebuilt {edges} edges."
        )
        return 0

    if args.command == "focus":
        _print_atoms(store.focus_atoms(limit=args.limit))
        return 0

    if args.command == "show":
        try:
            atom = store.get_atom(args.id)
        except KeyError:
            print(f"atom not found: {args.id}", file=sys.stderr)
            return 2
        _print_atom_detail(atom)
        return 0

    if args.command == "digest":
        atoms = store.list_atoms()
        if not atoms:
            print("memory database is empty; ingest chats before building notes.")
            return 2
        notes = build_notes_from_atoms(
            atoms,
            min_atoms=args.min_atoms,
            max_points=args.max_points,
        )
        inserted = store.replace_notes(notes)
        print(f"Built {inserted} digested notes from {len(atoms)} thought atoms.")
        return 0

    if args.command == "notes":
        _print_notes(store.list_notes(limit=args.limit))
        return 0

    if args.command == "show-note":
        try:
            note = store.get_note(args.id)
        except KeyError:
            print(f"note not found: {args.id}", file=sys.stderr)
            return 2
        _print_note_detail(note)
        return 0

    if args.command == "export-vault":
        try:
            result = export_obsidian_vault(store, args.path)
        except ValueError as exc:
            print(str(exc))
            return 2
        print(f"Exported {result.notes_exported} notes to {result.path.resolve()}")
        print(f"Manifest: {result.manifest_path.resolve()}")
        return 0

    if args.command == "refresh":
        source_candidates = sources_for_labels(args.source, home=args.home) if args.source else []
        try:
            result = refresh_memory(
                db_path=args.db,
                input_path=args.input,
                input_paths=[source.path for source in source_candidates],
                vault_path=args.vault,
                graph_path=args.graph,
                min_chars=args.min_chars,
                max_turns=args.max_turns,
                min_note_atoms=args.min_note_atoms,
                max_note_points=args.max_note_points,
            )
        except ValueError as exc:
            print(str(exc))
            return 2
        print(
            "Refresh complete: "
            f"imported={result.atoms_imported} atoms={result.atoms_after} "
            f"edges={result.edges_rebuilt} notes={result.notes_built} "
            f"vault_notes={result.vault_notes_exported}"
        )
        if result.graph_path:
            print(f"Graph: {result.graph_path.resolve()}")
        return 0

    if args.command == "sources":
        candidates = discover_sources(home=args.home)
        if not candidates:
            print("No allowlisted Codex/Claude conversation sources found.")
            return 0
        for source in candidates:
            print(f"{source.label}\t{source.kind}\t{source.path}")
        return 0

    if args.command == "app":
        config = default_app_config(args.db)
        if args.dry_run:
            print("Sporepath desktop app")
            print(f"db={config.db_path}")
            print(f"vault={config.vault_path}")
            print(f"graph={config.graph_path}")
            return 0
        from .app import run_app

        run_app(config)
        return 0

    if args.command == "graph":
        out = export_graph_html(store, args.out, limit=args.limit)
        print(f"Wrote {out.resolve()}")
        return 0

    if args.command == "decay":
        changed = store.decay_all(factor=args.factor, floor=args.floor)
        print(f"Decayed {changed} atoms.")
        return 0

    if args.command == "touch":
        store.touch_atoms(args.ids, amount=args.amount)
        print(f"Touched {len(args.ids)} atoms.")
        return 0

    if args.command == "inspire":
        focus_atoms = store.focus_atoms(limit=args.focus_limit)
        latent_atoms = store.latent_candidates(args.question, limit=args.latent_limit)
        if not focus_atoms and not latent_atoms:
            print(
                "memory database is empty; ingest a ChatGPT/Claude/Codex export first, "
                "or test with examples\\sample.sqlite."
            )
            print(
                "Example: python -m sporepath --db my_memory.sqlite ingest "
                "$env:USERPROFILE\\Downloads\\conversations.json"
            )
            return 2
        prompt = build_inspiration_prompt(
            question=args.question,
            focus_atoms=focus_atoms,
            latent_atoms=latent_atoms,
        )
        if args.dry_run:
            print(prompt)
            return 0
        if not shutil.which("codex"):
            print("codex executable was not found on PATH. Run with --dry-run or install/login to Codex.", file=sys.stderr)
            return 2
        result = run_codex_exec(prompt, cwd=str(Path.cwd()), timeout_s=args.timeout_s)
        if result.returncode != 0 and result.stderr.strip():
            print(result.stderr, file=sys.stderr)
        print(result.stdout)
        if result.returncode == 0:
            store.touch_atoms([atom.id for atom in focus_atoms + latent_atoms[:3]], amount=0.08)
        return result.returncode

    if args.command == "stats":
        stats = store.stats()
        print(f"atoms={stats['atoms']} edges={stats['edges']} notes={stats['notes']}")
        return 0

    if args.command == "doctor":
        codex_path = shutil.which("codex")
        print(f"python={sys.executable}")
        print(f"codex={codex_path or '(not found)'}")
        if codex_path:
            status = subprocess.run(
                codex_command(["login", "status"]),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            status_text = (status.stdout or status.stderr).strip()
            print(f"codex_login_status={status_text or '(no output)'}")
        print(f"ollama_status={_ollama_status()}")
        print("billing_guard=CODEX_API_KEY and OPENAI_API_KEY are removed for inspire subprocesses")
        print("auth_note=verify `codex` is logged in with ChatGPT subscription, not API-key auth")
        return 0

    return 1


def _print_atoms(atoms) -> None:
    for atom in atoms:
        tags = ", ".join(atom.tags)
        print(
            f"{atom.id} [{atom.kind}] activation={atom.activation:.2f} "
            f"importance={atom.importance:.2f} tags=[{tags}] {atom.summary}"
        )


def _print_notes(notes) -> None:
    for note in notes:
        tags = ", ".join(note.tags)
        print(
            f"{note.id} [{note.note_type}] activation={note.activation:.2f} "
            f"tags=[{tags}] {note.title}"
        )


def _print_atom_detail(atom) -> None:
    tags = ", ".join(atom.tags)
    print(f"id: {atom.id}")
    print(f"source: {atom.source}")
    print(f"role: {atom.role}")
    print(f"kind: {atom.kind}")
    print(f"tags: [{tags}]")
    print(f"timestamp: {atom.timestamp or '(unknown)'}")
    print(f"importance: {atom.importance:.2f}")
    print(f"activation: {atom.activation:.2f}")
    print("")
    print("summary:")
    print(atom.summary)
    print("")
    print("text:")
    print(atom.text)
    if atom.metadata:
        print("")
        print("metadata:")
        for key in sorted(atom.metadata):
            print(f"{key}: {atom.metadata[key]}")


def _print_note_detail(note) -> None:
    tags = ", ".join(note.tags)
    print(f"id: {note.id}")
    print(f"type: {note.note_type}")
    print(f"title: {note.title}")
    print(f"tags: [{tags}]")
    print(f"activation: {note.activation:.2f}")
    print("")
    print("summary:")
    print(note.summary)
    print("")
    print("key points:")
    for point in note.key_points:
        print(f"- {point}")
    if note.open_questions:
        print("")
        print("open questions:")
        for question in note.open_questions:
            print(f"- {question}")
    print("")
    print("source atoms:")
    for atom_id in note.source_atom_ids:
        print(f"- {atom_id}")
    print("")
    print("source spans:")
    for source in note.source_spans:
        print(f"- {source}")
    if note.metadata:
        print("")
        print("metadata:")
        for key in sorted(note.metadata):
            print(f"{key}: {note.metadata[key]}")


def _ollama_status(host: str = "http://127.0.0.1:11434") -> str:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=1.5) as response:
            data = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return "not reachable; start Ollama before using --extractor ollama"
    return "reachable" if data else "reachable, empty response"


if __name__ == "__main__":
    raise SystemExit(main())
