from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Button, Entry, Frame, Label, StringVar, Text, Tk, filedialog

from .app_config import AppConfig
from .automation import sync_arcrift_memory
from .codex_adapter import build_inspiration_prompt, parse_inspiration_suggestions, run_codex_exec
from .digest_queue import collect_fragments_from_files, process_digest_queue
from .graph_export import export_graph_html
from .notes import build_notes_from_atoms
from .refresh import refresh_memory
from .source_discovery import discover_sources
from .store import MemoryStore
from .vault_export import export_obsidian_vault, sync_obsidian_vault


def run_app(config: AppConfig) -> None:
    root = Tk()
    root.title("Sporepath")
    root.geometry("860x680")
    app = SporepathApp(root, config)
    app.pack(fill=BOTH, expand=True)
    root.mainloop()


class SporepathApp(Frame):
    def __init__(self, master: Tk, config: AppConfig):
        super().__init__(master, padx=12, pady=12)
        self.db_var = StringVar(value=str(config.db_path))
        self.input_var = StringVar(value=str(config.input_path or ""))
        self.arcrift_var = StringVar(value=str(config.arcrift_path or ""))
        self.vault_var = StringVar(value=str(config.vault_path))
        self.graph_var = StringVar(value=str(config.graph_path))
        self.suggestion_var = StringVar(value="1")
        self.detected_source_paths: list[Path] = []
        self.last_inspire_run_id: str | None = None
        self.question: Text
        self.output: Text
        self._build()

    def _build(self) -> None:
        self._path_row("Memory DB", self.db_var, browse_file=True)
        self._path_row("Chat Export", self.input_var, browse_file=True)
        self._path_row("ArcRift DB", self.arcrift_var, browse_file=True)
        self._path_row("Obsidian Vault", self.vault_var, browse_dir=True)
        self._path_row("Graph HTML", self.graph_var, browse_file=True)

        button_row = Frame(self)
        button_row.pack(fill="x", pady=(8, 12))
        Button(button_row, text="Auto-detect Sources", command=self.detect_sources).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Import ArcRift", command=self.import_arcrift).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Refresh Now", command=self.refresh_now).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Sync Vault", command=self.sync_vault).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Open Vault", command=self.open_vault).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Queue Status", command=self.queue_status).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Run Queue Batch", command=self.run_queue_batch).pack(side=LEFT)

        Label(self, text="Question for Inspire").pack(anchor="w")
        self.question = Text(self, height=5, wrap="word")
        self.question.pack(fill="x", pady=(4, 8))
        inspire_row = Frame(self)
        inspire_row.pack(fill="x", pady=(0, 12))
        Button(inspire_row, text="Inspire", command=self.inspire).pack(side=LEFT, padx=(0, 8))
        Label(inspire_row, text="Suggestion id").pack(side=LEFT, padx=(0, 4))
        Entry(inspire_row, textvariable=self.suggestion_var, width=8).pack(side=LEFT, padx=(0, 8))
        Button(inspire_row, text="Mark Useful", command=self.mark_inspire_useful).pack(side=LEFT)

        Label(self, text="Output").pack(anchor="w")
        self.output = Text(self, height=20, wrap="word")
        self.output.pack(fill=BOTH, expand=True, pady=(4, 0))
        self._write("Ready.\n")

    def _path_row(
        self,
        label: str,
        variable: StringVar,
        *,
        browse_file: bool = False,
        browse_dir: bool = False,
    ) -> None:
        row = Frame(self)
        row.pack(fill="x", pady=3)
        Label(row, text=label, width=14, anchor="w").pack(side=LEFT)
        Entry(row, textvariable=variable).pack(side=LEFT, fill="x", expand=True, padx=(0, 8))
        if browse_file:
            Button(row, text="Browse", command=lambda: self._browse_file(variable)).pack(side=RIGHT)
        if browse_dir:
            Button(row, text="Browse", command=lambda: self._browse_dir(variable)).pack(side=RIGHT)

    def _browse_file(self, variable: StringVar) -> None:
        path = filedialog.askopenfilename()
        if path:
            variable.set(path)

    def _browse_dir(self, variable: StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def refresh_now(self) -> None:
        self._run_background(self._refresh_worker)

    def import_arcrift(self) -> None:
        self._run_background(self._arcrift_worker)

    def detect_sources(self) -> None:
        sources = discover_sources()
        self.detected_source_paths = [source.path for source in sources]
        if not sources:
            self._write("No Codex/Claude conversation sources found.\n")
            return
        self._write("Detected sources:\n")
        for source in sources:
            self._write(f"- {source.label}: {source.path}\n")

    def open_vault(self) -> None:
        vault = Path(self.vault_var.get())
        vault.mkdir(parents=True, exist_ok=True)
        os.startfile(vault)
        self._write(f"Opened vault: {vault.resolve()}\n")

    def sync_vault(self) -> None:
        self._run_background(self._sync_worker)

    def inspire(self) -> None:
        self._run_background(self._inspire_worker)

    def queue_status(self) -> None:
        self._run_background(self._queue_status_worker)

    def run_queue_batch(self) -> None:
        self._run_background(self._queue_batch_worker)

    def mark_inspire_useful(self) -> None:
        run_id = self.last_inspire_run_id
        suggestion_id = self.suggestion_var.get().strip()
        self._run_background(lambda: self._feedback_worker(run_id, suggestion_id))

    def _refresh_worker(self) -> str:
        input_text = self.input_var.get().strip()
        input_paths = self.detected_source_paths if not input_text else None
        result = refresh_memory(
            db_path=self.db_var.get(),
            input_path=input_text or None,
            input_paths=input_paths,
            vault_path=self.vault_var.get(),
            graph_path=self.graph_var.get(),
        )
        return (
            "Refresh complete.\n"
            f"atoms_imported={result.atoms_imported} atoms={result.atoms_after} "
            f"edges={result.edges_rebuilt} notes={result.notes_built} "
            f"vault_notes={result.vault_notes_exported}\n"
        )

    def _sync_worker(self) -> str:
        result = sync_obsidian_vault(MemoryStore(self.db_var.get()), self.vault_var.get())
        return (
            "Vault sync complete.\n"
            f"modified_notes={result.notes_touched} touched_atoms={result.atoms_touched}\n"
        )

    def _queue_status_worker(self) -> str:
        store = MemoryStore(self.db_var.get())
        stats = store.queue_stats()
        lines = [
            "Queue status.",
            f"pending={stats.get('pending', 0)} done={stats.get('done', 0)} "
            f"skipped={stats.get('skipped', 0)} error={stats.get('error', 0)}",
        ]
        errors = store.queue_errors(limit=3)
        if errors:
            lines.append("Recent errors:")
            for row in errors:
                lines.append(f"- {row['id']}: {row['last_error']}")
        return "\n".join(lines) + "\n"

    def _queue_batch_worker(self) -> str:
        store = MemoryStore(self.db_var.get())
        input_text = self.input_var.get().strip()
        input_paths = [Path(input_text)] if input_text else self.detected_source_paths
        enqueued = 0
        if input_paths:
            fragments = collect_fragments_from_files(input_paths, min_chars=80)
            enqueued = store.enqueue_fragments(fragments)

        result = process_digest_queue(store, extractor=None, limit=5)
        edges = 0
        notes_built = 0
        vault_notes = 0
        graph_written = None
        if result.atoms_created:
            edges = store.rebuild_edges()
            notes = build_notes_from_atoms(store.list_atoms())
            notes_built = store.replace_notes(notes)
            if notes:
                vault_notes = export_obsidian_vault(store, self.vault_var.get()).notes_exported
            graph_written = export_graph_html(store, self.graph_var.get())
        stats = store.queue_stats()
        return (
            "Queue batch complete.\n"
            f"enqueued={enqueued} processed={result.processed} atoms_created={result.atoms_created} "
            f"skipped={result.skipped} errors={result.errors} edges={edges} "
            f"notes={notes_built} vault_notes={vault_notes} pending={stats.get('pending', 0)}\n"
            f"graph={Path(graph_written).resolve() if graph_written else '(not written)'}\n"
        )

    def _arcrift_worker(self) -> str:
        arcrift_path = self.arcrift_var.get().strip()
        if not arcrift_path:
            return "Choose an ArcRift DB first.\n"
        result = sync_arcrift_memory(
            db_path=self.db_var.get(),
            arcrift_db_path=arcrift_path,
            vault_path=self.vault_var.get(),
            graph_path=self.graph_var.get(),
        )
        return (
            "ArcRift import complete.\n"
            f"atoms_imported={result.atoms_imported} atoms={result.atoms_after} "
            f"edges={result.edges_rebuilt} notes={result.notes_built} "
            f"vault_notes={result.vault_notes_exported}\n"
            f"graph={result.graph_path.resolve() if result.graph_path else '(not written)'}\n"
        )

    def _inspire_worker(self) -> str:
        question = self.question.get("1.0", END).strip()
        if not question:
            return "Type a question first.\n"
        store = MemoryStore(self.db_var.get())
        focus_atoms = store.focus_atoms(limit=6)
        focus_atom_ids = [atom.id for atom in focus_atoms]
        latent_atoms = store.latent_candidates(question, limit=12, focus_atom_ids=focus_atom_ids)
        if not focus_atoms and not latent_atoms:
            return "Memory database is empty. Refresh or ingest chats first.\n"
        prompt = build_inspiration_prompt(
            question=question,
            focus_atoms=focus_atoms,
            latent_atoms=latent_atoms,
        )
        result = run_codex_exec(prompt, cwd=str(Path.cwd()), timeout_s=300)
        if result.returncode == 0:
            latent_atom_ids = [atom.id for atom in latent_atoms]
            run_id = store.record_inspire_run(
                question=question,
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
            self.last_inspire_run_id = run_id
            suggestion_ids = ",".join(str(suggestion["suggestion_id"]) for suggestion in suggestions)
            suffix = f" suggestions={suggestion_ids}" if suggestion_count else ""
            result_text = f"{result.stdout}\n\ninspire_run={run_id}{suffix}\n"
        else:
            result_text = result.stdout
        if result.stderr.strip():
            return result_text + "\n" + result.stderr
        return result_text

    def _feedback_worker(self, run_id: str | None, suggestion_id: str) -> str:
        if not run_id:
            return "Run Inspire first, then mark a suggestion useful.\n"
        if not suggestion_id:
            return "Type the suggestion id to mark.\n"
        result = MemoryStore(self.db_var.get()).apply_inspire_feedback(
            run_id,
            suggestion_id=suggestion_id,
            status="useful",
            note="marked useful from desktop app",
        )
        return (
            "Inspire feedback recorded.\n"
            f"run={run_id} suggestion={suggestion_id} "
            f"atoms_touched={result['atoms_touched']} "
            f"bridges_strengthened={result['bridges_strengthened']}\n"
        )

    def _run_background(self, func) -> None:
        def runner() -> None:
            try:
                message = func()
            except Exception as exc:
                message = f"Error: {exc}\n"
            self.after(0, lambda: self._write(message))

        threading.Thread(target=runner, daemon=True).start()

    def _write(self, text: str) -> None:
        self.output.insert(END, text)
        self.output.see(END)
