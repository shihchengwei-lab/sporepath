from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .arcrift_import import extract_atoms_from_arcrift_db
from .app_config import default_app_config
from .automation import sync_arcrift_memory
from .codex_adapter import build_inspiration_prompt, codex_command, parse_inspiration_suggestions, run_codex_exec
from .digest_queue import collect_fragments_from_files, is_off_peak_window, process_digest_queue
from .evaluation import build_extraction_eval, score_eval_sheet
from .extractors import OllamaExtractor
from .graph_export import export_graph_html
from .ingest import extract_atoms_from_file
from .notes import build_notes_from_atoms
from .refresh import refresh_memory
from .source_discovery import discover_sources, expand_source_files, sources_for_labels
from .source_watch import build_source_snapshot, source_snapshot_changed
from .store import MemoryStore
from .vault_export import export_obsidian_vault, sync_obsidian_vault


DEFAULT_DB = Path("memory.sqlite")


def _build_extractor(args):
    if args.extractor != "ollama":
        return None
    return OllamaExtractor(
        model=args.model,
        host=args.ollama_host,
        timeout_s=args.ollama_timeout_s,
        num_predict=args.ollama_num_predict,
        min_confidence=args.min_confidence,
    )


def _enqueue_queue_inputs(store: MemoryStore, args) -> int:
    source_candidates = sources_for_labels(args.source, home=args.home) if args.source else []
    input_paths = [*args.input, *source_candidates]
    if not input_paths:
        return 0
    files = expand_source_files(input_paths)
    fragments = collect_fragments_from_files(
        files,
        min_chars=args.min_chars,
        max_turns=args.max_turns,
    )
    return store.enqueue_fragments(fragments)


def _refresh_queue_outputs(store: MemoryStore, args, *, atoms_created: int) -> dict[str, object]:
    result: dict[str, object] = {
        "edges": 0,
        "notes": 0,
        "vault_notes": 0,
        "graph": None,
    }
    if not atoms_created:
        return result
    if not getattr(args, "skip_rebuild_edges", False):
        result["edges"] = store.rebuild_edges()
    notes = build_notes_from_atoms(
        store.list_atoms(),
        min_atoms=args.min_note_atoms,
        max_points=args.max_note_points,
    )
    result["notes"] = store.replace_notes(notes)
    if args.vault and notes:
        result["vault_notes"] = export_obsidian_vault(store, args.vault).notes_exported
    if args.graph:
        result["graph"] = export_graph_html(store, args.graph)
    return result


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
    ingest.add_argument("--ollama-timeout-s", type=int, default=60)
    ingest.add_argument("--ollama-num-predict", type=int, default=220)
    ingest.add_argument("--min-confidence", type=float, default=0.55)

    import_arcrift = sub.add_parser("import-arcrift", help="Import full chats from an ArcRift SQLite database.")
    import_arcrift.add_argument("path")
    import_arcrift.add_argument("--project", default=None, help="Optional ArcRift project name or session id to import.")
    import_arcrift.add_argument("--min-chars", type=int, default=12)
    import_arcrift.add_argument("--max-turns", type=int, default=None)
    import_arcrift.add_argument("--extractor", choices=["rules", "ollama"], default="rules")
    import_arcrift.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model for --extractor ollama.")
    import_arcrift.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    import_arcrift.add_argument("--ollama-timeout-s", type=int, default=60)
    import_arcrift.add_argument("--ollama-num-predict", type=int, default=220)
    import_arcrift.add_argument("--min-confidence", type=float, default=0.55)

    sync_arcrift = sub.add_parser("sync-arcrift", help="Import ArcRift DB, rebuild notes, export vault, and refresh graph once.")
    sync_arcrift.add_argument("--arcrift-db", default=None, help="Path to ArcRift.db. Auto-detected when omitted.")
    sync_arcrift.add_argument("--project", default=None, help="Optional ArcRift project name or session id to import.")
    sync_arcrift.add_argument("--vault", default=None, help="Optional Obsidian vault output path.")
    sync_arcrift.add_argument("--graph", default=None, help="Optional graph HTML output path.")
    sync_arcrift.add_argument("--min-chars", type=int, default=12)
    sync_arcrift.add_argument("--max-turns", type=int, default=None)
    sync_arcrift.add_argument("--min-note-atoms", type=int, default=1)
    sync_arcrift.add_argument("--max-note-points", type=int, default=5)

    watch_arcrift = sub.add_parser("watch-arcrift", help="Continuously sync ArcRift DB into notes and graph.")
    watch_arcrift.add_argument("--arcrift-db", default=None, help="Path to ArcRift.db. Auto-detected when omitted.")
    watch_arcrift.add_argument("--project", default=None, help="Optional ArcRift project name or session id to import.")
    watch_arcrift.add_argument("--vault", default=None, help="Optional Obsidian vault output path.")
    watch_arcrift.add_argument("--graph", default=None, help="Optional graph HTML output path.")
    watch_arcrift.add_argument("--interval-s", type=float, default=20.0)
    watch_arcrift.add_argument("--once", action="store_true", help="Run one sync and exit.")
    watch_arcrift.add_argument("--min-chars", type=int, default=12)
    watch_arcrift.add_argument("--max-turns", type=int, default=None)
    watch_arcrift.add_argument("--min-note-atoms", type=int, default=1)
    watch_arcrift.add_argument("--max-note-points", type=int, default=5)

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

    sync_vault = sub.add_parser("sync-vault", help="Touch notes and atoms edited in an exported Obsidian vault.")
    sync_vault.add_argument("path")
    sync_vault.add_argument("--touch-amount", type=float, default=0.15)

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

    watch_sources = sub.add_parser("watch-sources", help="Continuously refresh from local Codex/Claude/JSONL sources.")
    watch_sources.add_argument("--input", action="append", default=[], help="Additional JSON/JSONL file or directory to watch.")
    watch_sources.add_argument("--source", action="append", default=[], help="Auto-detected source family or label: all, codex, claude, codex_history, claude_projects, etc.")
    watch_sources.add_argument("--home", default=None, help="Override home directory for source detection.")
    watch_sources.add_argument("--vault", default=None, help="Optional Obsidian vault output path.")
    watch_sources.add_argument("--graph", default=None, help="Optional graph HTML output path.")
    watch_sources.add_argument("--interval-s", type=float, default=20.0)
    watch_sources.add_argument("--once", action="store_true", help="Run one refresh and exit.")
    watch_sources.add_argument("--min-chars", type=int, default=12)
    watch_sources.add_argument("--max-turns", type=int, default=None)
    watch_sources.add_argument("--min-note-atoms", type=int, default=2)
    watch_sources.add_argument("--max-note-points", type=int, default=5)

    queue_build = sub.add_parser("queue-build", help="Collect raw chat fragments into the background digestion queue.")
    queue_build.add_argument("--input", action="append", default=[], help="JSON/JSONL file or directory to queue.")
    queue_build.add_argument("--source", action="append", default=[], help="Auto-detected source family or label.")
    queue_build.add_argument("--home", default=None, help="Override home directory for source detection.")
    queue_build.add_argument("--min-chars", type=int, default=12)
    queue_build.add_argument("--max-turns", type=int, default=None)

    digest_queue = sub.add_parser("digest-queue", help="Process queued fragments during idle/off-peak time.")
    digest_queue.add_argument("--limit", type=int, default=10)
    digest_queue.add_argument("--extractor", choices=["rules", "ollama"], default="rules")
    digest_queue.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model for --extractor ollama.")
    digest_queue.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    digest_queue.add_argument("--ollama-timeout-s", type=int, default=60)
    digest_queue.add_argument("--ollama-num-predict", type=int, default=220)
    digest_queue.add_argument("--min-confidence", type=float, default=0.55)
    digest_queue.add_argument("--skip-rebuild-edges", action="store_true")
    digest_queue.add_argument("--vault", default=None, help="Optional Obsidian vault output path to refresh after new atoms.")
    digest_queue.add_argument("--graph", default=None, help="Optional graph HTML output path to refresh after new atoms.")
    digest_queue.add_argument("--min-note-atoms", type=int, default=2)
    digest_queue.add_argument("--max-note-points", type=int, default=5)

    queue_worker = sub.add_parser("queue-worker", help="Continuously process the digestion queue during an off-peak window.")
    queue_worker.add_argument("--input", action="append", default=[], help="JSON/JSONL file or directory to collect into the queue each tick.")
    queue_worker.add_argument("--source", action="append", default=[], help="Auto-detected source family or label to collect into the queue each tick.")
    queue_worker.add_argument("--home", default=None, help="Override home directory for source detection.")
    queue_worker.add_argument("--off-peak", default="00:00-07:00", help="Allowed processing window, e.g. 00:00-07:00.")
    queue_worker.add_argument("--batch-size", type=int, default=5)
    queue_worker.add_argument("--interval-s", type=float, default=300.0)
    queue_worker.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    queue_worker.add_argument("--run-now", action="store_true", help="Ignore --off-peak for this run.")
    queue_worker.add_argument("--min-chars", type=int, default=80)
    queue_worker.add_argument("--max-turns", type=int, default=None)
    queue_worker.add_argument("--extractor", choices=["rules", "ollama"], default="rules")
    queue_worker.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model for --extractor ollama.")
    queue_worker.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    queue_worker.add_argument("--ollama-timeout-s", type=int, default=60)
    queue_worker.add_argument("--ollama-num-predict", type=int, default=220)
    queue_worker.add_argument("--min-confidence", type=float, default=0.55)
    queue_worker.add_argument("--vault", default=None, help="Optional Obsidian vault output path to refresh after new atoms.")
    queue_worker.add_argument("--graph", default=None, help="Optional graph HTML output path to refresh after new atoms.")
    queue_worker.add_argument("--min-note-atoms", type=int, default=2)
    queue_worker.add_argument("--max-note-points", type=int, default=5)

    sub.add_parser("queue-stats", help="Show background digestion queue status counts.")
    queue_errors = sub.add_parser("queue-errors", help="List queued fragments that failed extraction.")
    queue_errors.add_argument("--limit", type=int, default=20)
    queue_retry = sub.add_parser("queue-retry", help="Move failed queue fragments back to pending.")
    queue_retry.add_argument("ids", nargs="*", help="Optional fragment ids. If omitted, all error fragments are retried.")

    eval_extract = sub.add_parser("eval-extract", help="Build an extraction eval sheet from chat sources.")
    eval_extract.add_argument("--input", action="append", default=[], help="JSON/JSONL file or directory to sample.")
    eval_extract.add_argument("--source", action="append", default=[], help="Auto-detected source family or label.")
    eval_extract.add_argument("--home", default=None, help="Override home directory for source detection.")
    eval_extract.add_argument("--out", default="eval/extraction_eval.jsonl", help="Output JSONL eval sheet.")
    eval_extract.add_argument("--report", default=None, help="Optional Markdown review report path.")
    eval_extract.add_argument("--limit", type=int, default=20)
    eval_extract.add_argument("--min-chars", type=int, default=40)
    eval_extract.add_argument("--max-chars", type=int, default=1600, help="Skip fragments longer than this; use 0 to disable.")
    eval_extract.add_argument("--max-turns", type=int, default=None)
    eval_extract.add_argument("--contains", action="append", default=[], help="Only include fragments containing this keyword; can be repeated.")
    eval_extract.add_argument("--extractor", choices=["rules", "ollama"], default="rules")
    eval_extract.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model for --extractor ollama.")
    eval_extract.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    eval_extract.add_argument("--ollama-timeout-s", type=int, default=60)
    eval_extract.add_argument("--ollama-num-predict", type=int, default=220)
    eval_extract.add_argument("--min-confidence", type=float, default=0.55)

    eval_score = sub.add_parser("eval-score", help="Summarize a filled extraction eval JSONL sheet.")
    eval_score.add_argument("path")

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

    inspire_feedback = sub.add_parser("inspire-feedback", help="Mark an inspire result as useful/applied and strengthen selected bridges.")
    inspire_feedback.add_argument("run_id")
    inspire_feedback.add_argument("--status", required=True, choices=["selected", "useful", "applied", "boring", "wrong", "ignored"])
    inspire_feedback.add_argument("--atoms", nargs="+", default=None, help="Atom ids cited by the selected idea.")
    inspire_feedback.add_argument("--suggestion", default=None, help="Suggestion id printed inside the inspire result.")
    inspire_feedback.add_argument("--note", default="")
    inspire_feedback.add_argument("--amount", type=float, default=None)

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
                timeout_s=args.ollama_timeout_s,
                num_predict=args.ollama_num_predict,
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

    if args.command == "import-arcrift":
        extractor = None
        if args.extractor == "ollama":
            extractor = OllamaExtractor(
                model=args.model,
                host=args.ollama_host,
                timeout_s=args.ollama_timeout_s,
                num_predict=args.ollama_num_predict,
                min_confidence=args.min_confidence,
            )
        try:
            atoms = extract_atoms_from_arcrift_db(
                args.path,
                min_chars=args.min_chars,
                extractor=extractor,
                max_turns=args.max_turns,
                project=args.project,
            )
        except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        inserted = store.upsert_atoms(atoms)
        edges = store.rebuild_edges()
        project_label = f" project={args.project}" if args.project else ""
        print(
            f"Imported {inserted} ArcRift thought atoms{project_label} "
            f"with extractor={args.extractor}; rebuilt {edges} edges."
        )
        return 0

    if args.command in {"sync-arcrift", "watch-arcrift"}:
        config = default_app_config(args.db)
        vault_path = args.vault if args.vault is not None else str(config.vault_path)
        graph_path = args.graph if args.graph is not None else str(config.graph_path)
        while True:
            try:
                result = sync_arcrift_memory(
                    db_path=args.db,
                    arcrift_db_path=args.arcrift_db,
                    vault_path=vault_path,
                    graph_path=graph_path,
                    min_chars=args.min_chars,
                    max_turns=args.max_turns,
                    min_note_atoms=args.min_note_atoms,
                    max_note_points=args.max_note_points,
                    project=args.project,
                )
            except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(
                "ArcRift sync complete: "
                f"imported={result.atoms_imported} atoms={result.atoms_after} "
                f"edges={result.edges_rebuilt} notes={result.notes_built} "
                f"vault_notes={result.vault_notes_exported}"
            )
            if result.graph_path:
                print(f"Graph: {result.graph_path.resolve()}")
            if args.command == "sync-arcrift" or args.once:
                return 0
            sys.stdout.flush()
            time.sleep(max(1.0, args.interval_s))

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

    if args.command == "sync-vault":
        try:
            result = sync_obsidian_vault(store, args.path, touch_amount=args.touch_amount)
        except ValueError as exc:
            print(str(exc))
            return 2
        print(
            f"Synced {result.notes_touched} modified notes; "
            f"touched {result.atoms_touched} source atoms."
        )
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

    if args.command == "watch-sources":
        config = default_app_config(args.db)
        vault_path = args.vault if args.vault is not None else str(config.vault_path)
        graph_path = args.graph if args.graph is not None else str(config.graph_path)
        source_labels = args.source if args.source else ["all"]
        source_paths = [*sources_for_labels(source_labels, home=args.home), *args.input]
        if not source_paths:
            print("No local source paths found. Use --source codex/claude/all or --input <path>.", file=sys.stderr)
            return 2

        snapshot = None
        while True:
            should_refresh = snapshot is None or args.once or source_snapshot_changed(snapshot, source_paths)
            if should_refresh:
                try:
                    result = refresh_memory(
                        db_path=args.db,
                        input_paths=source_paths,
                        vault_path=vault_path,
                        graph_path=graph_path,
                        min_chars=args.min_chars,
                        max_turns=args.max_turns,
                        min_note_atoms=args.min_note_atoms,
                        max_note_points=args.max_note_points,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
                snapshot = build_source_snapshot(source_paths)
                print(
                    "Source sync complete: "
                    f"imported={result.atoms_imported} atoms={result.atoms_after} "
                    f"edges={result.edges_rebuilt} notes={result.notes_built} "
                    f"vault_notes={result.vault_notes_exported}"
                )
                if result.graph_path:
                    print(f"Graph: {result.graph_path.resolve()}")
                sys.stdout.flush()
            if args.once:
                return 0
            time.sleep(max(1.0, args.interval_s))

    if args.command == "queue-build":
        source_candidates = sources_for_labels(args.source, home=args.home) if args.source else []
        input_paths = [*args.input, *source_candidates]
        files = expand_source_files(input_paths)
        if not files:
            print("No queue input. Use --input <path> or --source codex/claude/all.", file=sys.stderr)
            return 2
        fragments = collect_fragments_from_files(
            files,
            min_chars=args.min_chars,
            max_turns=args.max_turns,
        )
        inserted = store.enqueue_fragments(fragments)
        stats = store.queue_stats()
        print(
            f"Enqueued {inserted} fragments "
            f"(pending={stats.get('pending', 0)} done={stats.get('done', 0)} "
            f"skipped={stats.get('skipped', 0)} error={stats.get('error', 0)})."
        )
        return 0

    if args.command == "digest-queue":
        extractor = _build_extractor(args)
        result = process_digest_queue(store, extractor=extractor, limit=args.limit)
        refreshed = _refresh_queue_outputs(store, args, atoms_created=result.atoms_created)
        stats = store.queue_stats()
        print(
            "Digest queue complete: "
            f"processed={result.processed} atoms_created={result.atoms_created} "
            f"skipped={result.skipped} errors={result.errors} edges={refreshed['edges']} "
            f"notes={refreshed['notes']} vault_notes={refreshed['vault_notes']} "
            f"pending={stats.get('pending', 0)}"
        )
        if refreshed["graph"]:
            print(f"Graph: {Path(refreshed['graph']).resolve()}")
        return 0

    if args.command == "queue-worker":
        extractor = _build_extractor(args)
        while True:
            enqueued = _enqueue_queue_inputs(store, args)
            now = datetime.now().time()
            should_run = args.run_now or is_off_peak_window(now, args.off_peak)
            if should_run:
                result = process_digest_queue(store, extractor=extractor, limit=args.batch_size)
                refreshed = _refresh_queue_outputs(store, args, atoms_created=result.atoms_created)
                stats = store.queue_stats()
                print(
                    "worker_tick=processed "
                    f"enqueued={enqueued} processed={result.processed} atoms_created={result.atoms_created} "
                    f"skipped={result.skipped} errors={result.errors} edges={refreshed['edges']} "
                    f"notes={refreshed['notes']} vault_notes={refreshed['vault_notes']} "
                    f"pending={stats.get('pending', 0)}"
                )
                if refreshed["graph"]:
                    print(f"Graph: {Path(refreshed['graph']).resolve()}")
            else:
                stats = store.queue_stats()
                print(
                    "worker_tick=idle "
                    f"off_peak={args.off_peak} enqueued={enqueued} pending={stats.get('pending', 0)}"
                )
            sys.stdout.flush()
            if args.once:
                return 0
            time.sleep(max(1.0, args.interval_s))

    if args.command == "queue-stats":
        stats = store.queue_stats()
        print(
            f"pending={stats.get('pending', 0)} done={stats.get('done', 0)} "
            f"skipped={stats.get('skipped', 0)} error={stats.get('error', 0)}"
        )
        return 0

    if args.command == "queue-errors":
        errors = store.queue_errors(limit=args.limit)
        if not errors:
            print("No queue errors.")
            return 0
        for row in errors:
            text = str(row["text"]).replace("\n", " ")[:120]
            print(
                f"{row['id']}\tattempts={row['attempts']}\t"
                f"source={row['source']}\terror={row['last_error']}\ttext={text}"
            )
        return 0

    if args.command == "queue-retry":
        changed = store.reset_queue_errors(args.ids or None)
        stats = store.queue_stats()
        print(
            f"Requeued {changed} error fragments. "
            f"pending={stats.get('pending', 0)} error={stats.get('error', 0)}"
        )
        return 0

    if args.command == "eval-extract":
        source_candidates = sources_for_labels(args.source, home=args.home) if args.source else []
        input_paths = [*args.input, *[source.path for source in source_candidates]]
        if not input_paths:
            print("No eval input. Use --input <path> or --source codex/claude/all.", file=sys.stderr)
            return 2
        extractor = None
        if args.extractor == "ollama":
            extractor = OllamaExtractor(
                model=args.model,
                host=args.ollama_host,
                timeout_s=args.ollama_timeout_s,
                num_predict=args.ollama_num_predict,
                min_confidence=args.min_confidence,
            )
        try:
            result = build_extraction_eval(
                input_paths=input_paths,
                out_path=args.out,
                report_path=args.report,
                extractor=extractor,
                extractor_name=args.extractor,
                limit=args.limit,
                min_chars=args.min_chars,
                max_chars=args.max_chars if args.max_chars > 0 else None,
                max_turns=args.max_turns,
                contains=args.contains,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Eval cases: {result.cases_written}")
        print(f"JSONL: {result.jsonl_path.resolve()}")
        print(f"Report: {result.report_path.resolve()}")
        return 0

    if args.command == "eval-score":
        result = score_eval_sheet(args.path)
        print(
            f"scored={result.scored_cases}/{result.total_cases} "
            f"pass_rate={result.pass_rate:.1%} "
            f"keep_agreement={result.keep_agreement:.1%} "
            f"route_agreement={result.route_agreement:.1%} "
            f"signal_found={result.signal_found_rate:.1%} "
            f"noise_marked={result.noise_marked_rate:.1%} "
            f"handoff_sufficient={result.handoff_sufficient_rate:.1%}"
        )
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
            print(f"arcrift={config.arcrift_path or ''}")
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
        focus_atom_ids = [atom.id for atom in focus_atoms]
        latent_atoms = store.latent_candidates(
            args.question,
            limit=args.latent_limit,
            focus_atom_ids=focus_atom_ids,
        )
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
            latent_atom_ids = [atom.id for atom in latent_atoms]
            run_id = store.record_inspire_run(
                question=args.question,
                focus_atom_ids=focus_atom_ids,
                latent_atom_ids=latent_atom_ids,
                output_text=result.stdout,
            )
            suggestions = parse_inspiration_suggestions(
                result.stdout,
                known_atom_ids=set(focus_atom_ids + latent_atom_ids),
            )
            suggestion_count = store.record_inspire_suggestions(run_id, suggestions)
            store.touch_atoms([atom.id for atom in focus_atoms + latent_atoms[:3]], amount=0.08)
            suggestion_ids = ",".join(str(suggestion["suggestion_id"]) for suggestion in suggestions)
            suffix = f" suggestions={suggestion_ids}" if suggestion_count else ""
            print(f"\ninspire_run={run_id}{suffix}")
        return result.returncode

    if args.command == "inspire-feedback":
        try:
            result = store.apply_inspire_feedback(
                args.run_id,
                atom_ids=args.atoms,
                suggestion_id=args.suggestion,
                status=args.status,
                note=args.note,
                amount=args.amount,
            )
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        parts = ["Inspire feedback recorded:", f"status={args.status}"]
        if args.suggestion:
            parts.append(f"suggestion={args.suggestion}")
        parts.extend(
            [
                f"atoms_touched={result['atoms_touched']}",
                f"bridges_strengthened={result['bridges_strengthened']}",
            ]
        )
        print(" ".join(parts))
        return 0

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
