from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .extractors import ExtractSignal, Extractor
from .extractors import route_from_kind
from .ingest import _clean_text, _is_tool_noise, _read_turns, classify_kind, infer_tags, score_importance, summarize
from .source_discovery import expand_source_files


@dataclass(frozen=True)
class ExtractionEvalResult:
    cases_written: int
    jsonl_path: Path
    report_path: Path


@dataclass(frozen=True)
class EvalScoreResult:
    total_cases: int
    scored_cases: int
    pass_rate: float
    noise_rate: float
    keep_agreement: float
    route_agreement: float
    signal_found_rate: float
    noise_marked_rate: float
    handoff_sufficient_rate: float
    avg_summary_quality: float
    avg_structure_quality: float


def build_extraction_eval(
    *,
    input_paths: Iterable[str | Path],
    out_path: str | Path,
    report_path: str | Path | None = None,
    extractor: Extractor | None = None,
    extractor_name: str = "rules",
    limit: int = 20,
    min_chars: int = 40,
    max_chars: int | None = 1600,
    max_turns: int | None = None,
    per_file_limit: int | None = None,
    checkpoint_every: int | None = None,
    contains: Iterable[str] | None = None,
) -> ExtractionEvalResult:
    files = expand_source_files(input_paths)
    if not files:
        raise ValueError("no JSON/JSONL input files found for eval")

    jsonl_path = Path(out_path)
    markdown_path = Path(report_path) if report_path is not None else jsonl_path.with_suffix(".md")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    needles = [needle.casefold() for needle in (contains or []) if needle.strip()]
    for source_file in files:
        turns_read = 0
        cases_from_file = 0
        for turn in _read_turns(source_file):
            if max_turns is not None and turns_read >= max_turns:
                break
            if per_file_limit is not None and cases_from_file >= per_file_limit:
                break
            turns_read += 1
            text = _clean_text(turn["text"])
            if _is_tool_noise(text) or len(text) < min_chars:
                continue
            if max_chars is not None and len(text) > max_chars:
                continue
            if needles and not any(needle in text.casefold() for needle in needles):
                continue
            role = turn.get("role", "unknown")
            source = turn.get("source") or f"{source_file.name}:turn[{turns_read - 1}]"
            prediction = _predict(text, role=role, extractor=extractor)
            records.append(
                {
                    "id": _case_id(source, text),
                    "source_file": str(source_file),
                    "source": source,
                    "role": role,
                    "text": text,
                    "extractor": extractor_name,
                    "prediction": prediction,
                    "human": _blank_human_review(),
                }
            )
            cases_from_file += 1
            if checkpoint_every and len(records) % checkpoint_every == 0:
                _write_jsonl(jsonl_path, records)
                _write_markdown(markdown_path, records)
            if len(records) >= limit:
                break
        if len(records) >= limit:
            break

    _write_jsonl(jsonl_path, records)
    _write_markdown(markdown_path, records)
    return ExtractionEvalResult(
        cases_written=len(records),
        jsonl_path=jsonl_path,
        report_path=markdown_path,
    )


def score_eval_sheet(path: str | Path) -> EvalScoreResult:
    records = _read_jsonl(Path(path))
    scored = [record for record in records if _is_scored(record.get("human", {}))]
    scored_count = len(scored)

    passed = 0
    summary_scores: list[float] = []
    structure_scores: list[float] = []
    noise_values: list[bool] = []
    keep_matches: list[bool] = []
    route_matches: list[bool] = []
    signal_found_values: list[bool] = []
    noise_marked_values: list[bool] = []
    handoff_values: list[bool] = []

    for record in scored:
        human = record.get("human", {})
        prediction = record.get("prediction") or {}
        useful = _as_bool(human.get("useful"))
        noise = _as_bool(human.get("noise"))
        summary_quality = _as_number(human.get("summary_quality"))
        structure_quality = _as_number(human.get("structure_quality"))
        signal_found = _as_bool(human.get("signal_found"))
        noise_marked = _as_bool(human.get("noise_marked"))
        handoff_sufficient = _as_bool(human.get("handoff_sufficient"))

        if summary_quality is not None:
            summary_scores.append(summary_quality)
        if structure_quality is not None:
            structure_scores.append(structure_quality)
        if noise is not None:
            noise_values.append(noise)
        if signal_found is not None:
            signal_found_values.append(signal_found)
        if noise_marked is not None:
            noise_marked_values.append(noise_marked)
        if handoff_sufficient is not None:
            handoff_values.append(handoff_sufficient)

        human_keep = _as_bool(human.get("keep"))
        predicted_keep = _as_bool(prediction.get("keep"))
        if human_keep is not None and predicted_keep is not None:
            keep_matches.append(human_keep == predicted_keep)

        human_route = str(human.get("route") or "").strip()
        predicted_route = str(prediction.get("route") or "").strip()
        if human_route and predicted_route:
            route_matches.append(human_route == predicted_route)

        has_scout_scores = any(
            value is not None
            for value in (signal_found, noise_marked, handoff_sufficient)
        )
        if has_scout_scores:
            if (
                useful is True
                and signal_found is True
                and handoff_sufficient is True
                and noise_marked is not False
            ):
                passed += 1
        elif (
            useful is True
            and noise is not True
            and (summary_quality is None or summary_quality >= 3)
            and (structure_quality is None or structure_quality >= 3)
        ):
            passed += 1

    return EvalScoreResult(
        total_cases=len(records),
        scored_cases=scored_count,
        pass_rate=(passed / scored_count) if scored_count else 0.0,
        noise_rate=(
            sum(1 for value in noise_values if value) / len(noise_values)
            if noise_values
            else 0.0
        ),
        keep_agreement=(
            sum(1 for value in keep_matches if value) / len(keep_matches)
            if keep_matches
            else 0.0
        ),
        route_agreement=(
            sum(1 for value in route_matches if value) / len(route_matches)
            if route_matches
            else 0.0
        ),
        signal_found_rate=(
            sum(1 for value in signal_found_values if value) / len(signal_found_values)
            if signal_found_values
            else 0.0
        ),
        noise_marked_rate=(
            sum(1 for value in noise_marked_values if value) / len(noise_marked_values)
            if noise_marked_values
            else 0.0
        ),
        handoff_sufficient_rate=(
            sum(1 for value in handoff_values if value) / len(handoff_values)
            if handoff_values
            else 0.0
        ),
        avg_summary_quality=_average(summary_scores),
        avg_structure_quality=_average(structure_scores),
    )


def _predict(text: str, *, role: str, extractor: Extractor | None) -> dict[str, Any]:
    if extractor is None:
        kind = classify_kind(text)
        tags = infer_tags(text)
        return {
            "keep": True,
            "route": route_from_kind(kind),
            "kind": kind,
            "summary": summarize(text),
            "signals": tags,
            "noise": [],
            "handoff": summarize(text),
            "tags": tags,
            "confidence": score_importance(role, text, kind, tags),
            "reason": "rules baseline",
        }

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
    return {
        "keep": signal.keep,
        "route": signal.route,
        "kind": signal.kind,
        "summary": signal.summary,
        "signals": signal.signals,
        "noise": signal.noise,
        "handoff": signal.handoff,
        "tags": signal.tags,
        "confidence": signal.confidence,
        "reason": signal.reason,
    }


def _blank_human_review() -> dict[str, Any]:
    return {
        "keep": None,
        "route": "",
        "signal_found": None,
        "noise_marked": None,
        "handoff_sufficient": None,
        "useful": None,
        "notes": "",
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )


def _write_markdown(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [
        "# Sporepath Scout Eval",
        "",
        "Review each case, then fill the matching `human` fields in the JSONL file.",
        "Judge the local model as a scout: keep/discard, routing, reusable signals, noise handling, and handoff sufficiency.",
        "",
    ]
    for index, record in enumerate(records, start=1):
        prediction = record["prediction"]
        lines.extend(
            [
                f"## {index}. {record['id']}",
                "",
                f"- Source: `{record['source']}`",
                f"- Role: `{record['role']}`",
                f"- Extractor: `{record['extractor']}`",
                f"- Prediction: keep={prediction['keep']} route=`{prediction['route']}` kind=`{prediction['kind']}` confidence={prediction['confidence']:.2f}",
                f"- Tags: {', '.join(f'`{tag}`' for tag in prediction['tags'])}",
                f"- Signals: {', '.join(f'`{signal}`' for signal in prediction['signals']) or '(none)'}",
                f"- Noise: {', '.join(f'`{noise}`' for noise in prediction['noise']) or '(none)'}",
                "",
                "Scout handoff:",
                "",
                f"> {prediction['handoff'] or '(empty)'}",
                "",
                "Rough summary:",
                "",
                f"> {prediction['summary'] or '(empty)'}",
                "",
                "Prediction reason:",
                "",
                f"> {prediction['reason'] or '(empty)'}",
                "",
                "Fragment:",
                "",
                "```text",
                _escape_fence(record["text"]),
                "```",
                "",
                "Human review fields in JSONL:",
                "",
                "- keep:",
                "- route:",
                "- signal_found:",
                "- noise_marked:",
                "- handoff_sufficient:",
                "- useful:",
                "- notes:",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def _case_id(source: str, text: str) -> str:
    return hashlib.sha1(f"{source}\n{text}".encode("utf-8")).hexdigest()[:16]


def _is_scored(human: dict[str, Any]) -> bool:
    return any(
        human.get(key) is not None and human.get(key) != ""
        for key in (
            "keep",
            "route",
            "signal_found",
            "noise_marked",
            "handoff_sufficient",
            "summary_quality",
            "structure_quality",
            "noise",
            "useful",
        )
    )


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in {"true", "yes", "y", "1"}:
            return True
        if folded in {"false", "no", "n", "0"}:
            return False
    return None


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _escape_fence(text: str) -> str:
    return text.replace("```", "'''")
