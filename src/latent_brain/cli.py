from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .codex_adapter import build_inspiration_prompt, codex_command, run_codex_exec
from .extractors import OllamaExtractor
from .graph_export import export_graph_html
from .ingest import extract_atoms_from_file
from .store import MemoryStore


DEFAULT_DB = Path("memory.sqlite")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="latent-brain")
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
                "Example: python -m latent_brain --db my_memory.sqlite ingest "
                "C:\\path\\to\\conversations.json"
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
        print(f"atoms={stats['atoms']} edges={stats['edges']}")
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


def _ollama_status(host: str = "http://127.0.0.1:11434") -> str:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=1.5) as response:
            data = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return "not reachable; start Ollama before using --extractor ollama"
    return "reachable" if data else "reachable, empty response"


if __name__ == "__main__":
    raise SystemExit(main())
