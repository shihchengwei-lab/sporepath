from __future__ import annotations

import os
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
    return f"""你是這個 PoC 的創意橋接器，不是筆記摘要器。

當前卡住的問題：
{question}

當前加粗的專注路徑：
{focus_block}

沉到潛意識、但可能被重新喚醒的候選片段：
{latent_block}

請輸出 3 個「怪但有橋」的下一手。規則：
- 不要泛泛聯想，不要吹捧，不要把候選片段硬湊成漂亮話。
- 每一手都要引用至少一個候選片段的 id 或 source。
- 說清楚：舊片段、為什麼現在可能重新有用、跟當前問題的橋、下一步怎麼驗證。
- 如果候選片段都沒用，直接說不夠好，並說需要什麼資料。
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
    return (
        f"- id={atom.id} source={atom.source} kind={atom.kind} "
        f"activation={atom.activation:.2f} tags=[{tags}] summary={atom.summary}"
    )
