from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from .models import ThoughtAtom


@dataclass(frozen=True)
class CodexResult:
    stdout: str
    stderr: str
    returncode: int


def build_inspiration_prompt(
    *,
    question: str,
    focus_atoms: list[ThoughtAtom],
    latent_atoms: list[ThoughtAtom],
) -> str:
    focus_block = "\n".join(_format_atom(atom) for atom in focus_atoms) or "(none)"
    latent_block = "\n".join(_format_atom(atom) for atom in latent_atoms) or "(none)"
    return f"""You are Sporepath's inspiration bridge, not a note summarizer.

Current stuck question:
{question}

Focus paths that are currently thick:
{focus_block}

Latent candidates that have low activation but may become useful now:
{latent_block}

Write exactly 3 weird-but-bridged next moves.

Rules:
- Do not summarize the notes.
- Do not give generic advice such as "do user interviews" unless a cited atom
  makes that move non-obvious.
- Every suggestion must cite at least one candidate atom id in `cited_atom_ids`.
- Prefer a useful weak bridge over the most similar memory.
- Explain why the old atom matters now and what concrete next action it implies.
- If the candidates are not enough, say what evidence is missing instead of
  inventing a bridge.

Use this exact block format for each suggestion:
suggestion_id: 1
cited_atom_ids: [atom_id_1, atom_id_2]
title: ...
bridge: ...
why_now: ...
next_step: ...
validation: ...
"""


def run_codex_exec(prompt: str, *, cwd: str | None = None, timeout_s: int = 300) -> CodexResult:
    env = os.environ.copy()
    # Avoid accidentally switching this PoC to API-key billing through per-run env vars.
    env.pop("CODEX_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    completed = subprocess.run(
        codex_command(
            [
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "-c",
                'model_reasoning_effort="low"',
                "-",
            ]
        ),
        cwd=cwd,
        env=env,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return CodexResult(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        returncode=completed.returncode,
    )


def codex_command(args: list[str]) -> list[str]:
    codex = shutil.which("codex") or "codex"
    lowered = codex.casefold()
    if os.name == "nt" and lowered.endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/c", codex, *args]
    if os.name == "nt" and lowered.endswith(".ps1"):
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", codex, *args]
    return [codex, *args]


def _format_atom(atom: ThoughtAtom) -> str:
    tags = ", ".join(atom.tags)
    metadata = atom.metadata or {}
    scout_parts = []
    route = metadata.get("extractor_route")
    if route:
        scout_parts.append(f"route={route}")
    signals = _metadata_list(metadata.get("extractor_signals"))
    if signals:
        scout_parts.append(f"signals=[{', '.join(signals)}]")
    handoff = metadata.get("extractor_handoff")
    if handoff:
        scout_parts.append(f"handoff={handoff}")
    noise = _metadata_list(metadata.get("extractor_noise"))
    if noise:
        scout_parts.append(f"noise=[{', '.join(noise)}]")
    scout = f" scout=({' ; '.join(scout_parts)})" if scout_parts else ""
    return (
        f"- id={atom.id} source={atom.source} kind={atom.kind} "
        f"activation={atom.activation:.2f} tags=[{tags}] summary={atom.summary}{scout}"
    )


def parse_inspiration_suggestions(
    output: str,
    *,
    known_atom_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    lines = output.splitlines()
    start_indexes: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"\s*suggestion_id\s*:\s*([A-Za-z0-9_.-]+)\s*$", line, re.IGNORECASE)
        if match:
            start_indexes.append((index, match.group(1)))

    suggestions: list[dict[str, object]] = []
    for offset, (start, suggestion_id) in enumerate(start_indexes):
        end = start_indexes[offset + 1][0] if offset + 1 < len(start_indexes) else len(lines)
        block_lines = [line.rstrip() for line in lines[start:end]]
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        block = "\n".join(block_lines).strip()
        cited_line = ""
        for line in block_lines:
            match = re.match(r"\s*cited_atom_ids\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
            if match:
                cited_line = match.group(1)
                break
        cited_atom_ids = _extract_cited_atom_ids(cited_line, known_atom_ids=known_atom_ids)
        if cited_atom_ids:
            suggestions.append(
                {
                    "suggestion_id": suggestion_id,
                    "cited_atom_ids": cited_atom_ids,
                    "text": block,
                }
            )
    return suggestions


def _extract_cited_atom_ids(value: str, *, known_atom_ids: set[str] | None) -> list[str]:
    if not value:
        return []
    if known_atom_ids is not None:
        found = [atom_id for atom_id in known_atom_ids if re.search(rf"(?<![\w.-]){re.escape(atom_id)}(?![\w.-])", value)]
        return sorted(found, key=lambda atom_id: value.find(atom_id))
    cleaned = value.strip().strip("[]")
    tokens = [token.strip().strip("'\"`") for token in re.split(r"[,\s]+", cleaned)]
    return [token for token in tokens if token]


def _metadata_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []
