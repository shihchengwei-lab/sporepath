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
        min_confidence: float = 0.55,
        transport: Callable[[dict], str] | None = None,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.min_confidence = min_confidence
        self.transport = transport or self._ollama_chat

    def extract(self, text: str, role: str = "unknown") -> ExtractSignal:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.8,
                "num_predict": 220,
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract reusable thought atoms from AI chat logs. "
                        "Return only one compact JSON object. No markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": build_extraction_prompt(text, role=role),
                },
            ],
        }
        raw = self.transport(payload)
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
    return f"""你是聊天記憶哨兵，不是筆記編輯器。只輸出 JSON，不要 markdown，不要解釋。

任務：判斷下面片段是否值得成為「候選記憶」，並留下足夠線索給後續 digest / inspire 使用。

保留條件：它包含未來可重用的想法、問題、決策、偏好、判斷框架、反對點、類比，或可能重複踩到的技術坑。
丟棄條件：寒暄、工具噪音、暫時性輸出、空泛摘要、沒有可重用判斷。

route 只能選一個：
debug, product, preference, idea, decision, research, writing, ops, other

kind 只能選一個：
idea, objection, decision, question, analogy, preference, taste, framework, bug_memory, note

輸出格式必須是單一 JSON object，欄位如下：
- keep: boolean
- route: string，大致路由，給後續系統決定交給哪種 digest / inspire
- kind: string
- summary: string，粗略記憶，不要求漂亮，不要只複製全文
- signals: array of 1 to 5 reusable signals，抓可重用訊號，不要寫完整句
- noise: array of strings，列出應丟掉的寒暄、情緒、工具或一次性內容；沒有就 []
- handoff: string，給後續雲端模型思考的短線索，重點是「這可能在什麼情境有用」
- tags: array of 2 to 6 short strings，不可使用 placeholder
- confidence: number from 0 to 1
- reason: string

role: {role}
fragment:
<<<
{text}
>>>
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
    noise = _string_list(data.get("noise", []), limit=8)
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


def route_from_kind(kind: str) -> str:
    return KIND_TO_ROUTE.get(kind, "other")


def _loads_jsonish(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
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
