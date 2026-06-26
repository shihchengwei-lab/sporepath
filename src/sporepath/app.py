from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Button, Entry, Frame, Label, StringVar, Text, Tk, filedialog

from .app_config import AppConfig
from .codex_adapter import build_inspiration_prompt, run_codex_exec
from .refresh import refresh_memory
from .source_discovery import discover_sources
from .store import MemoryStore


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
        self.vault_var = StringVar(value=str(config.vault_path))
        self.graph_var = StringVar(value=str(config.graph_path))
        self.detected_source_paths: list[Path] = []
        self.question: Text
        self.output: Text
        self._build()

    def _build(self) -> None:
        self._path_row("Memory DB", self.db_var, browse_file=True)
        self._path_row("Chat Export", self.input_var, browse_file=True)
        self._path_row("Obsidian Vault", self.vault_var, browse_dir=True)
        self._path_row("Graph HTML", self.graph_var, browse_file=True)

        button_row = Frame(self)
        button_row.pack(fill="x", pady=(8, 12))
        Button(button_row, text="Auto-detect Sources", command=self.detect_sources).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Refresh Now", command=self.refresh_now).pack(side=LEFT, padx=(0, 8))
        Button(button_row, text="Open Vault", command=self.open_vault).pack(side=LEFT, padx=(0, 8))

        Label(self, text="Question for Inspire").pack(anchor="w")
        self.question = Text(self, height=5, wrap="word")
        self.question.pack(fill="x", pady=(4, 8))
        Button(self, text="Inspire", command=self.inspire).pack(anchor="w", pady=(0, 12))

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

    def inspire(self) -> None:
        self._run_background(self._inspire_worker)

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

    def _inspire_worker(self) -> str:
        question = self.question.get("1.0", END).strip()
        if not question:
            return "Type a question first.\n"
        store = MemoryStore(self.db_var.get())
        focus_atoms = store.focus_atoms(limit=6)
        latent_atoms = store.latent_candidates(question, limit=12)
        if not focus_atoms and not latent_atoms:
            return "Memory database is empty. Refresh or ingest chats first.\n"
        prompt = build_inspiration_prompt(
            question=question,
            focus_atoms=focus_atoms,
            latent_atoms=latent_atoms,
        )
        result = run_codex_exec(prompt, cwd=str(Path.cwd()), timeout_s=300)
        if result.returncode == 0:
            store.touch_atoms([atom.id for atom in focus_atoms + latent_atoms[:3]], amount=0.08)
        if result.stderr.strip():
            return result.stdout + "\n" + result.stderr
        return result.stdout

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
