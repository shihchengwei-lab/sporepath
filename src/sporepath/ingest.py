from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .extractors import ExtractSignal, Extractor
from .models import ThoughtAtom


TAG_RULES: dict[str, tuple[str, ...]] = {
    "second-brain": ("第二大腦", "second brain", "second-brain"),
    "ai-memory": ("ai memory", "記憶", "memory", "長期脈絡"),
    "local-first": ("本地", "local", "隱私", "privacy"),
    "slime-mold": ("黏菌", "slime", "路徑加粗", "沉降", "衰退"),
    "inspiration": ("靈感", "創意", "發散", "神之一手", "breakthrough"),
    "go": ("圍棋", "神之一手"),
    "poc": ("poc", "原型", "最小", "mvp"),
    "codex": ("codex", "codex exec"),
    "claude": ("claude", "claude code"),
    "jsonl": ("jsonl", "json"),
    "embedding": ("embedding", "向量"),
}

KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("objection", ("風險", "危險", "打槍", "反對", "不行", "不能", "問題是", "risk", "flaw", "however")),
    ("decision", ("決定", "結論", "所以我會", "先做", "不要做", "cut", "decide")),
    ("question", ("?", "？", "怎麼", "如何", "為什麼", "what if", "how do")),
    ("idea", ("我想", "想法", "可以做", "能不能", "maybe", "idea", "could")),
    ("analogy", ("像", "類比", "比喻", "圍棋", "神之一手", "黏菌")),
    ("preference", ("我喜歡", "我不想", "偏好", "不要", "prefer")),
)


def extract_atoms_from_file(
    path: str | Path,
    *,
    min_chars: int = 12,
    extractor: Extractor | None = None,
    max_turns: int | None = None,
) -> list[ThoughtAtom]:
    path = Path(path)
    turns = list(_read_turns(path))
    atoms: list[ThoughtAtom] = []
    for index, turn in enumerate(turns[:max_turns] if max_turns is not None else turns):
        text = _clean_text(turn["text"])
        if _is_tool_noise(text):
            continue
        if len(text) < min_chars:
            continue
        source = turn.get("source") or f"{path.name}:{index}"
        role = turn.get("role", "unknown")
        if extractor is None:
            atoms.append(_atom_from_turn(path, source, role, text, turn.get("timestamp")))
            continue
        try:
            signal = extractor.extract(text, role=role)
        except Exception as exc:
            signal = ExtractSignal(
                keep=False,
                kind="note",
                summary="",
                tags=["extractor-error"],
                confidence=0.0,
                reason=str(exc),
            )
        if not signal.keep:
            continue
        atoms.append(_atom_from_signal(path, source, role, text, turn.get("timestamp"), signal))
    return atoms


def _read_turns(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        yield from _read_jsonl_turns(path)
        return

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "conversations" in payload:
        payload = payload["conversations"]

    if _looks_like_chatgpt_export(payload):
        yield from _read_chatgpt_export(path, payload)
        return

    if isinstance(payload, dict) and "messages" in payload:
        yield from _read_messages(path, payload["messages"], prefix=path.name)
        return

    if isinstance(payload, list):
        for idx, row in enumerate(payload):
            if isinstance(row, dict) and "messages" in row:
                yield from _read_messages(path, row["messages"], prefix=f"{path.name}:conversation[{idx}]")
            elif isinstance(row, dict):
                text = _message_text(row)
                if text:
                    yield {
                        "source": f"{path.name}:row[{idx}]",
                        "role": row.get("role") or row.get("author") or "unknown",
                        "text": text,
                        "timestamp": _normalize_timestamp(row.get("timestamp") or row.get("create_time")),
                    }


def _read_jsonl_turns(path: Path) -> Iterable[dict[str, Any]]:
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "messages" in row:
            yield from _read_messages(path, row["messages"], prefix=f"{path.name}:line[{index}]")
            continue
        if not isinstance(row, dict):
            continue
        text = _message_text(row)
        if not text:
            continue
        yield {
            "source": f"{path.name}:line[{index}]",
            "role": row.get("role") or row.get("author") or "unknown",
            "text": text,
            "timestamp": _normalize_timestamp(row.get("timestamp") or row.get("create_time")),
        }


def _read_chatgpt_export(path: Path, conversations: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for conv_index, conversation in enumerate(conversations):
        mapping = conversation.get("mapping") or {}
        rows: list[tuple[float, str, dict[str, Any]]] = []
        for node_id, node in mapping.items():
            message = node.get("message") if isinstance(node, dict) else None
            if not message:
                continue
            created = message.get("create_time") or 0
            try:
                sort_time = float(created)
            except (TypeError, ValueError):
                sort_time = 0.0
            rows.append((sort_time, node_id, message))

        for _, node_id, message in sorted(rows, key=lambda row: row[0]):
            text = _message_text(message)
            if not text:
                continue
            author = message.get("author") or {}
            yield {
                "source": f"{path.name}:conversation[{conv_index}]/{node_id}",
                "role": author.get("role", "unknown"),
                "text": text,
                "timestamp": _normalize_timestamp(message.get("create_time")),
            }


def _read_messages(path: Path, messages: list[dict[str, Any]], *, prefix: str) -> Iterable[dict[str, Any]]:
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        text = _message_text(message)
        if not text:
            continue
        yield {
            "source": f"{prefix}:message[{index}]",
            "role": message.get("role") or message.get("author") or "unknown",
            "text": text,
            "timestamp": _normalize_timestamp(message.get("timestamp") or message.get("create_time")),
        }


def _looks_like_chatgpt_export(payload: Any) -> bool:
    return isinstance(payload, list) and any(isinstance(item, dict) and "mapping" in item for item in payload)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_part_text(part) for part in content if _part_text(part))
    if isinstance(content, dict):
        if "parts" in content and isinstance(content["parts"], list):
            return "\n".join(_part_text(part) for part in content["parts"] if _part_text(part))
        if isinstance(content.get("text"), str):
            return content["text"]
    if isinstance(message.get("text"), str):
        return message["text"]
    if isinstance(message.get("message"), str):
        return message["message"]
    return ""


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        if isinstance(part.get("text"), str):
            return part["text"]
        if isinstance(part.get("content"), str):
            return part["content"]
    return ""


def _atom_from_turn(path: Path, source: str, role: str, text: str, timestamp: str | None) -> ThoughtAtom:
    kind = classify_kind(text)
    tags = infer_tags(text)
    importance = score_importance(role, text, kind, tags)
    atom_id = hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]
    return ThoughtAtom(
        id=atom_id,
        source=source,
        role=role,
        text=text,
        summary=summarize(text),
        kind=kind,
        tags=tags,
        timestamp=timestamp,
        importance=importance,
        activation=min(0.65, max(0.1, importance * 0.65)),
        metadata={"source_file": str(path)},
    )


def _atom_from_signal(
    path: Path,
    source: str,
    role: str,
    text: str,
    timestamp: str | None,
    signal: ExtractSignal,
) -> ThoughtAtom:
    atom_id = hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]
    importance = round(min(0.95, max(0.05, 0.25 + signal.confidence * 0.55)), 3)
    summary = signal.handoff or signal.summary or summarize(text)
    return ThoughtAtom(
        id=atom_id,
        source=source,
        role=role,
        text=text,
        summary=summary,
        kind=signal.kind,
        tags=signal.tags,
        timestamp=timestamp,
        importance=importance,
        activation=min(0.65, max(0.08, importance * 0.55)),
        metadata={
            "source_file": str(path),
            "extractor": "local-llm",
            "extractor_confidence": signal.confidence,
            "extractor_reason": signal.reason,
            "extractor_route": signal.route,
            "extractor_signals": signal.signals,
            "extractor_noise": signal.noise,
            "extractor_handoff": signal.handoff,
        },
    )


def classify_kind(text: str) -> str:
    folded = text.casefold()
    for kind, needles in KIND_RULES:
        if any(needle.casefold() in folded for needle in needles):
            return kind
    return "note"


def infer_tags(text: str) -> list[str]:
    folded = text.casefold()
    tags = [
        tag
        for tag, needles in TAG_RULES.items()
        if any(needle.casefold() in folded for needle in needles)
    ]
    return tags or ["uncategorized"]


def summarize(text: str, *, limit: int = 96) -> str:
    first = re.split(r"[\n。！？!?]", text.strip(), maxsplit=1)[0].strip()
    if len(first) <= limit:
        return first
    return first[: limit - 1].rstrip() + "..."


def score_importance(role: str, text: str, kind: str, tags: list[str]) -> float:
    score = 0.2
    if role == "user":
        score += 0.15
    if kind in {"idea", "decision", "question"}:
        score += 0.2
    elif kind in {"objection", "analogy"}:
        score += 0.15
    score += min(0.15, len(tags) * 0.03)
    if len(text) > 120:
        score += 0.08
    return round(min(0.95, max(0.05, score)), 3)


def _clean_text(text: str) -> str:
    text = re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _is_tool_noise(text: str) -> bool:
    lowered = text.strip().casefold()
    return (
        lowered.startswith("<task-notification")
        or lowered.startswith("<tool-use")
        or lowered.startswith("<command-output")
        or lowered.startswith("<local-command")
    )


def _normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    return None
