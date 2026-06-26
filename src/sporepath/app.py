from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Button, Entry, Frame, Label, Radiobutton, StringVar, Text, Tk, Toplevel, filedialog

from .app_config import AppConfig, save_app_config
from .automation import sync_arcrift_memory
from .codex_adapter import build_inspiration_prompt, parse_inspiration_suggestions, run_codex_exec
from .digest_queue import collect_fragments_from_arcrift_db, collect_fragments_from_files, process_digest_queue
from .graph_export import export_graph_html
from .notes import build_notes_from_atoms
from .refresh import refresh_memory
from .source_discovery import discover_sources
from .store import MemoryStore
from .vault_export import export_obsidian_vault, sync_obsidian_vault


PRIMARY_ACTION_LABELS = ("Sync Vault", "Debug", "Inspire")
INSPIRE_RATING_OPTIONS = (("up", "👍", "useful"), ("down", "👎", "wrong"))
DEBUG_ACTION_LABELS = (
    "Auto-detect Sources",
    "Import ArcRift",
    "Refresh Now",
    "Open Vault",
    "Queue Status",
    "Run Queue Batch",
)


def should_show_feedback_controls(run_id: str | None, suggestion_count: int) -> bool:
    return bool(run_id) and suggestion_count > 0


def feedback_status_from_rating(rating: str) -> str:
    if not rating:
        return "ignored"
    for value, _label, status in INSPIRE_RATING_OPTIONS:
        if rating == value:
            return status
    raise ValueError(f"unsupported inspire rating: {rating}")


def feedback_statuses_for_suggestions(
    suggestion_ids: list[str],
    ratings: dict[str, str],
) -> dict[str, str]:
    return {
        suggestion_id: feedback_status_from_rating(ratings.get(suggestion_id, ""))
        for suggestion_id in suggestion_ids
    }


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
        self.detected_source_paths: list[Path] = []
        self.last_inspire_run_id: str | None = None
        self.last_inspire_suggestion_count = 0
        self.last_inspire_suggestion_ids: list[str] = []
        self.feedback_vars: dict[str, StringVar] = {}
        self.debug_window: Toplevel | None = None
        self.feedback_row: Frame
        self.inspire_row: Frame
        self.output_label: Label
        self.question: Text
        self.output: Text
        self._build()

    def _build(self) -> None:
        primary_row = Frame(self)
        primary_row.pack(fill="x", pady=(0, 12))
        Button(primary_row, text=PRIMARY_ACTION_LABELS[0], command=self.sync_vault).pack(side=LEFT, padx=(0, 8))
        Button(primary_row, text=PRIMARY_ACTION_LABELS[1], command=self.open_debug_panel).pack(side=LEFT)

        Label(self, text="Question for Inspire").pack(anchor="w")
        self.question = Text(self, height=5, wrap="word")
        self.question.pack(fill="x", pady=(4, 8))
        self.inspire_row = Frame(self)
        self.inspire_row.pack(fill="x", pady=(0, 12))
        Button(self.inspire_row, text=PRIMARY_ACTION_LABELS[2], command=self.inspire).pack(side=LEFT)

        self.feedback_row = Frame(self)
        self.feedback_row.pack(fill="x", pady=(0, 12))
        self.feedback_row.pack_forget()

        self.output_label = Label(self, text="Output")
        self.output_label.pack(anchor="w")
        self.output = Text(self, height=20, wrap="word")
        self.output.pack(fill=BOTH, expand=True, pady=(4, 0))
        self._write("Ready.\n")

    def _path_row(
        self,
        parent: Frame | Toplevel,
        label: str,
        variable: StringVar,
        *,
        browse_file: bool = False,
        browse_dir: bool = False,
    ) -> None:
        row = Frame(parent)
        row.pack(fill="x", pady=3)
        Label(row, text=label, width=14, anchor="w").pack(side=LEFT)
        Entry(row, textvariable=variable).pack(side=LEFT, fill="x", expand=True, padx=(0, 8))
        if browse_file:
            Button(row, text="Browse", command=lambda: self._browse_file(variable)).pack(side=RIGHT)
        if browse_dir:
            Button(row, text="Browse", command=lambda: self._browse_dir(variable)).pack(side=RIGHT)

    def open_debug_panel(self) -> None:
        if self.debug_window is not None and self.debug_window.winfo_exists():
            self.debug_window.lift()
            return
        window = Toplevel(self)
        self.debug_window = window
        window.title("Sporepath Debug")
        window.geometry("820x360")
        window.protocol("WM_DELETE_WINDOW", self._close_debug_panel)

        panel = Frame(window, padx=12, pady=12)
        panel.pack(fill=BOTH, expand=True)
        self._path_row(panel, "Memory DB", self.db_var, browse_file=True)
        self._path_row(panel, "Chat Export", self.input_var, browse_file=True)
        self._path_row(panel, "ArcRift DB", self.arcrift_var, browse_file=True)
        self._path_row(panel, "Obsidian Vault", self.vault_var, browse_dir=True)
        self._path_row(panel, "Graph HTML", self.graph_var, browse_file=True)

        debug_row = Frame(panel)
        debug_row.pack(fill="x", pady=(10, 0))
        debug_actions = (
            (DEBUG_ACTION_LABELS[0], self.detect_sources),
            (DEBUG_ACTION_LABELS[1], self.import_arcrift),
            (DEBUG_ACTION_LABELS[2], self.refresh_now),
            (DEBUG_ACTION_LABELS[3], self.open_vault),
            (DEBUG_ACTION_LABELS[4], self.queue_status),
            (DEBUG_ACTION_LABELS[5], self.run_queue_batch),
        )
        for label, command in debug_actions:
            Button(debug_row, text=label, command=command).pack(side=LEFT, padx=(0, 8))

    def _close_debug_panel(self) -> None:
        self.save_settings()
        if self.debug_window is not None and self.debug_window.winfo_exists():
            self.debug_window.destroy()
        self.debug_window = None

    def _show_feedback_controls(self) -> None:
        if not should_show_feedback_controls(self.last_inspire_run_id, self.last_inspire_suggestion_count):
            return
        for child in self.feedback_row.winfo_children():
            child.destroy()
        self.feedback_vars = {}
        Label(self.feedback_row, text="Rate inspire suggestions").pack(anchor="w")
        for suggestion_id in self.last_inspire_suggestion_ids:
            rating_var = StringVar(value="")
            self.feedback_vars[suggestion_id] = rating_var
            row = Frame(self.feedback_row)
            row.pack(fill="x", pady=2)
            Label(row, text=f"Suggestion {suggestion_id}", width=14, anchor="w").pack(side=LEFT)
            for value, label, _status in INSPIRE_RATING_OPTIONS:
                Radiobutton(row, text=label, variable=rating_var, value=value).pack(side=LEFT, padx=(0, 8))
        Button(self.feedback_row, text="Submit Feedback", command=self.submit_inspire_feedback).pack(anchor="w", pady=(6, 0))
        if not self.feedback_row.winfo_ismapped():
            self.feedback_row.pack(fill="x", pady=(0, 12), before=self.output_label)

    def _hide_feedback_controls(self) -> None:
        self.feedback_row.pack_forget()

    def _browse_file(self, variable: StringVar) -> None:
        path = filedialog.askopenfilename()
        if path:
            variable.set(path)
            self.save_settings()

    def _browse_dir(self, variable: StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)
            self.save_settings()

    def _current_config(self) -> AppConfig:
        input_text = self.input_var.get().strip()
        arcrift_text = self.arcrift_var.get().strip()
        return AppConfig(
            db_path=Path(self.db_var.get()),
            input_path=Path(input_text) if input_text else None,
            arcrift_path=Path(arcrift_text) if arcrift_text else None,
            vault_path=Path(self.vault_var.get()),
            graph_path=Path(self.graph_var.get()),
        )

    def save_settings(self) -> None:
        save_app_config(self._current_config(), base_dir=Path.cwd())

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
        self.save_settings()
        vault = Path(self.vault_var.get())
        vault.mkdir(parents=True, exist_ok=True)
        os.startfile(vault)
        self._write(f"Opened vault: {vault.resolve()}\n")

    def sync_vault(self) -> None:
        self._run_background(self._sync_worker)

    def inspire(self) -> None:
        self.last_inspire_run_id = None
        self.last_inspire_suggestion_count = 0
        self.last_inspire_suggestion_ids = []
        self._hide_feedback_controls()
        self._run_background(self._inspire_worker, after_success=self._show_feedback_controls)

    def queue_status(self) -> None:
        self._run_background(self._queue_status_worker)

    def run_queue_batch(self) -> None:
        self._run_background(self._queue_batch_worker)

    def submit_inspire_feedback(self) -> None:
        run_id = self.last_inspire_run_id
        raw_ratings = {
            suggestion_id: rating_var.get()
            for suggestion_id, rating_var in self.feedback_vars.items()
        }
        statuses = feedback_statuses_for_suggestions(self.last_inspire_suggestion_ids, raw_ratings)
        self._run_background(lambda: self._feedback_worker(run_id, statuses))

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
        arcrift_text = self.arcrift_var.get().strip()
        if arcrift_text:
            arcrift_fragments = collect_fragments_from_arcrift_db(arcrift_text, min_chars=80)
            enqueued += store.enqueue_fragments(arcrift_fragments)

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
            self.last_inspire_suggestion_count = suggestion_count
            self.last_inspire_suggestion_ids = [str(suggestion["suggestion_id"]) for suggestion in suggestions]
            suggestion_ids = ",".join(str(suggestion["suggestion_id"]) for suggestion in suggestions)
            suffix = f" suggestions={suggestion_ids}" if suggestion_count else ""
            result_text = f"{result.stdout}\n\ninspire_run={run_id}{suffix}\n"
        else:
            result_text = result.stdout
        if result.stderr.strip():
            return result_text + "\n" + result.stderr
        return result_text

    def _feedback_worker(self, run_id: str | None, statuses: dict[str, str]) -> str:
        if not run_id:
            return "Run Inspire first, then submit feedback.\n"
        if not statuses:
            return "Run Inspire first, then submit feedback.\n"
        store = MemoryStore(self.db_var.get())
        atoms_touched = 0
        bridges_strengthened = 0
        recorded = 0
        for suggestion_id, status in statuses.items():
            result = store.apply_inspire_feedback(
                run_id,
                suggestion_id=suggestion_id,
                status=status,
            )
            recorded += 1
            atoms_touched += result["atoms_touched"]
            bridges_strengthened += result["bridges_strengthened"]
        return (
            "Inspire feedback recorded.\n"
            f"run={run_id} ratings={recorded} "
            f"atoms_touched={atoms_touched} "
            f"bridges_strengthened={bridges_strengthened}\n"
        )

    def _run_background(self, func, *, after_success=None) -> None:
        self.save_settings()

        def runner() -> None:
            success = True
            try:
                message = func()
            except Exception as exc:
                success = False
                message = f"Error: {exc}\n"
            self.after(0, lambda: self._finish_background(message, success, after_success))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_background(self, message: str, success: bool, after_success) -> None:
        self._write(message)
        if success and after_success:
            after_success()

    def _write(self, text: str) -> None:
        self.output.insert(END, text)
        self.output.see(END)
