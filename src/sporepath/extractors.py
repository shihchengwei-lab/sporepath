from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol


VALID_KINDS = {
    "idea",
    "objection",
    "decision",
    "question",
    "analogy",
    "preference",
    "taste",
    "framework",
    "bug_memory",
    "note",
}

VALID_ROUTES = {
    "debug",
    "product",
    "preference",
    "idea",
    "decision",
    "research",
    "writing",
    "ops",
    "other",
}

KIND_TO_ROUTE = {
    "bug_memory": "debug",
    "taste": "preference",
    "preference": "preference",
    "decision": "decision",
    "question": "research",
    "framework": "decision",
    "idea": "idea",
}


@dataclass(frozen=True)
class ExtractSignal:
    keep: bool
    kind: str
    summary: str
    tags: list[str]
    confidence: float
    reason: str
    route: str = "other"
    signals: list[str] = field(default_factory=list)
    noise: list[str] = field(default_factory=list)
    handoff: str = ""


@dataclass(frozen=True)
class ExtractorCheckResult:
    ok: bool
    reason: str
    raw_preview: str = ""


class Extractor(Protocol):
    def extract(self, text: str, role: str = "unknown") -> ExtractSignal:
        ...


class OllamaExtractor:
    def __init__(
        self,
        *,
        model: str = "qwen3:1.7b",
        host: str = "http://127.0.0.1:11434",
        timeout_s: int = 60,
        num_predict: int = 220,
        min_confidence: float = 0.55,
        transport: Callable[[dict], str] | None = None,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.num_predict = num_predict
        self.min_confidence = min_confidence
        self.transport = transport or self._ollama_chat

    def check_canary(self) -> ExtractorCheckResult:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.8,
                "num_predict": min(self.num_predict, 180),
            },
            "messages": [
                {
                    "role": "system",
                    "content": "You are a chat-memory scout. Output exactly one JSON object and no markdown.",
                },
                {
                    "role": "user",
                    "content": build_extraction_prompt(
                        "Add support for TSV input. Keep tests green.",
                        role="user",
                    ),
                },
            ],
        }
        try:
            raw = self.transport(payload)
            if is_degenerate_model_output(raw):
                return ExtractorCheckResult(
                    ok=False,
                    reason="degenerate model output",
                    raw_preview=raw.strip()[:120],
                )
            parse_signal_json(raw)
        except Exception as exc:
            return ExtractorCheckResult(
                ok=False,
                reason=str(exc),
                raw_preview=raw.strip()[:120] if "raw" in locals() else "",
            )
        return ExtractorCheckResult(ok=True, reason="ok", raw_preview=raw.strip()[:120])

    def extract(self, text: str, role: str = "unknown") -> ExtractSignal:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.8,
                "num_predict": self.num_predict,
            },
            "messages": [
                {
                    "role": "system",
                    "content": "You are a chat-memory scout. Output exactly one JSON object and no markdown.",
                },
                {
                    "role": "user",
                    "content": build_extraction_prompt(text, role=role),
                },
            ],
        }
        raw = self.transport(payload)
        if is_degenerate_model_output(raw):
            raise ValueError("degenerate model output")
        signal = parse_signal_json(raw)
        if signal.confidence < self.min_confidence:
            return ExtractSignal(
                keep=False,
                kind=signal.kind,
                summary=signal.summary,
                tags=signal.tags,
                confidence=signal.confidence,
                reason=f"below min_confidence: {signal.reason}",
                route=signal.route,
                signals=signal.signals,
                noise=signal.noise,
                handoff=signal.handoff,
            )
        return signal

    def _ollama_chat(self, payload: dict) -> str:
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host}. Start Ollama and pull {self.model}."
            ) from exc
        parsed = json.loads(body)
        message = parsed.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama response did not contain message.content")
        return content


def build_extraction_prompt(text: str, *, role: str) -> str:
    return f"""fragment_text: {json.dumps(text, ensure_ascii=False)}
role: {role}

Decide whether fragment_text is worth keeping for future memory use.

Output exactly one JSON object with these fields:
keep, route, kind, summary, signals, noise, handoff, tags, confidence, reason.

keep=true when the fragment contains a reusable idea, problem, decision,
preference, judgment pattern, analogy, research lead, or technical pitfall.
keep=false when it is disposable progress chatter, tool noise, a stale recap,
empty status, or has no future use.

route must be one of:
debug, product, preference, idea, decision, research, writing, ops, other.

kind must be one of:
idea, objection, decision, question, analogy, preference, taste, framework,
bug_memory, note.

summary must name the concrete subject in fragment_text. Do not write vague
phrases like "unclear", "needs more analysis", or "may contain".

signals must list up to five reusable facts or judgments from fragment_text.
noise must list only exact disposable words or spans from fragment_text; use []
if there is no noise. Do not invent noise.

handoff must explain when this memory would help in the future. Do not mention
"digest" or "inspire" in handoff.

confidence must be between 0 and 1.
"""


def parse_signal_json(raw: str) -> ExtractSignal:
    data = _loads_jsonish(raw)
    keep = bool(data.get("keep", False))
    kind = str(data.get("kind", "note")).strip() or "note"
    if kind not in VALID_KINDS:
        kind = "note"
    route = _normalize_route(data.get("route"), kind)
    summary = str(data.get("summary", "")).strip()
    signals = _string_list(data.get("signals", []), limit=5)
    noise = _filter_placeholder_noise(_string_list(data.get("noise", []), limit=8))
    handoff = str(data.get("handoff", "")).strip()
    tags_raw = data.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [tag.strip() for tag in tags_raw.split(",")]
    elif isinstance(tags_raw, list):
        tags = [str(tag).strip() for tag in tags_raw]
    else:
        tags = []
    tags = [tag for tag in tags if tag][:6] or ["uncategorized"]
    confidence = _clamp_float(data.get("confidence", 0.0))
    reason = str(data.get("reason", "")).strip()
    return ExtractSignal(
        keep=keep,
        kind=kind,
        summary=summary,
        tags=tags,
        confidence=confidence,
        reason=reason,
        route=route,
        signals=signals,
        noise=noise,
        handoff=handoff,
    )


def is_degenerate_model_output(raw: str) -> bool:
    text = raw.strip()
    if len(text) < 8:
        return False
    return len(set(text)) == 1 and text[0].isdigit()


def route_from_kind(kind: str) -> str:
    return KIND_TO_ROUTE.get(kind, "other")


def _loads_jsonish(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    decoder = json.JSONDecoder()
    errors: list[json.JSONDecodeError] = []
    for match in re.finditer(r"\{", text):
        try:
            parsed, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError as exc:
            errors.append(exc)
            continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("extractor output must be a JSON object")
    if errors:
        raise errors[0]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("extractor output must be a JSON object")
    return parsed


def _clamp_float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize_route(raw, kind: str) -> str:
    route = str(raw or "").strip().casefold()
    if route in VALID_ROUTES:
        return route
    return route_from_kind(kind)


def _string_list(raw, *, limit: int) -> list[str]:
    if isinstance(raw, str):
        items = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(item).strip() for item in raw]
    else:
        items = []
    return [item for item in items if item][:limit]


def _filter_placeholder_noise(items: list[str]) -> list[str]:
    placeholders = {
        "無",
        "无",
        "none",
        "null",
        "n/a",
        "沒有",
        "没有",
        "寒暄、工具噪音、一次性進度",
    }
    result = []
    for item in items:
        folded = item.strip().casefold()
        if folded in placeholders:
            continue
        if "該丟掉的字" in item or "该丢掉的字" in item:
            continue
        result.append(item)
    return result
