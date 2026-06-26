from __future__ import annotations

import json
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .evaluation import score_eval_sheet
from .fragment_filter import fragment_fingerprint, is_disposable_fragment
from .store import MemoryStore


POSITIVE_INSPIRE_STATUSES = {"selected", "useful", "applied"}
MINIMUM_SCOUT_SCORED_CASES = 30


@dataclass(frozen=True)
class ValidationResult:
    name: str
    verdict: str
    metrics: dict[str, Any]
    markdown: str


def validate_scout(path: str | Path) -> ValidationResult:
    eval_path = Path(path)
    records = _read_jsonl(eval_path)
    score = score_eval_sheet(eval_path)
    predictions = [record.get("prediction") or {} for record in records]
    humans = [record.get("human") or {} for record in records]
    fingerprints = [fragment_fingerprint(str(record.get("text", ""))) for record in records]
    duplicate_count = sum(count - 1 for count in Counter(fingerprints).values() if count > 1)
    parse_error_count = sum(
        1 for prediction in predictions if "extractor-error" in (prediction.get("tags") or [])
    )
    tool_noise_retained_count = sum(
        1
        for record, prediction in zip(records, predictions)
        if prediction.get("keep") is True and is_disposable_fragment(str(record.get("text", "")))
    )
    false_negative_count = sum(
        1
        for human, prediction in zip(humans, predictions)
        if human.get("keep") is True and prediction.get("keep") is False
    )
    total = len(records)
    metrics = {
        "total_cases": total,
        "scored_cases": score.scored_cases,
        "minimum_scored_cases": MINIMUM_SCOUT_SCORED_CASES,
        "pass_rate": score.pass_rate,
        "keep_agreement": score.keep_agreement,
        "route_agreement": score.route_agreement,
        "handoff_sufficient_rate": score.handoff_sufficient_rate,
        "parse_error_count": parse_error_count,
        "parse_error_rate": _ratio(parse_error_count, total),
        "duplicate_count": duplicate_count,
        "duplicate_rate": _ratio(duplicate_count, total),
        "tool_noise_retained_count": tool_noise_retained_count,
        "tool_noise_retained_rate": _ratio(tool_noise_retained_count, total),
        "false_negative_count": false_negative_count,
        "false_negative_rate": _ratio(false_negative_count, score.scored_cases),
    }
    if total == 0 or score.scored_cases < MINIMUM_SCOUT_SCORED_CASES:
        verdict = "needs_data"
    elif (
        metrics["parse_error_rate"] <= 0.03
        and metrics["duplicate_rate"] <= 0.10
        and metrics["tool_noise_retained_rate"] <= 0.05
        and metrics["false_negative_rate"] <= 0.15
        and metrics["handoff_sufficient_rate"] >= 0.75
    ):
        verdict = "pass"
    else:
        verdict = "fail"
    return ValidationResult(
        name="Scout Validator",
        verdict=verdict,
        metrics=metrics,
        markdown=_render_scout_markdown(eval_path, verdict, metrics),
    )


def validate_notes(store: MemoryStore) -> ValidationResult:
    notes = store.list_notes()
    atoms = store.list_atoms()
    atom_ids = {atom.id for atom in atoms}
    notes_count = len(notes)
    empty_note_count = sum(1 for note in notes if not note.summary.strip() and not note.key_points)
    notes_with_sources = sum(1 for note in notes if note.source_atom_ids and note.source_spans)
    missing_source_note_count = sum(
        1 for note in notes if any(atom_id not in atom_ids for atom_id in note.source_atom_ids)
    )
    duplicate_title_count = sum(
        count - 1 for count in Counter(note.title.casefold() for note in notes).values() if count > 1
    )
    metrics = {
        "atoms_count": len(atoms),
        "notes_count": notes_count,
        "notes_with_sources": notes_with_sources,
        "notes_with_sources_rate": _ratio(notes_with_sources, notes_count),
        "empty_note_count": empty_note_count,
        "empty_note_rate": _ratio(empty_note_count, notes_count),
        "missing_source_note_count": missing_source_note_count,
        "missing_source_note_rate": _ratio(missing_source_note_count, notes_count),
        "duplicate_title_count": duplicate_title_count,
        "duplicate_title_rate": _ratio(duplicate_title_count, notes_count),
    }
    if notes_count == 0:
        verdict = "needs_data"
    elif (
        metrics["notes_with_sources_rate"] >= 1.0
        and empty_note_count == 0
        and missing_source_note_count == 0
        and metrics["duplicate_title_rate"] <= 0.20
    ):
        verdict = "pass"
    else:
        verdict = "fail"
    return ValidationResult(
        name="Notes Validator",
        verdict=verdict,
        metrics=metrics,
        markdown=_render_notes_markdown(verdict, metrics),
    )


def validate_inspire(store: MemoryStore) -> ValidationResult:
    with closing(store._connect()) as con:
        runs = con.execute(
            "SELECT id, latent_atom_ids FROM inspire_runs ORDER BY created_at ASC"
        ).fetchall()
        suggestions = con.execute(
            "SELECT run_id, suggestion_id, cited_atom_ids FROM inspire_suggestions"
        ).fetchall()
        feedback = con.execute("SELECT run_id, status FROM inspire_feedback").fetchall()

    run_ids = {row["id"] for row in runs}
    feedback_run_ids = {row["run_id"] for row in feedback}
    positive_feedback = [
        row for row in feedback if str(row["status"]).casefold() in POSITIVE_INSPIRE_STATUSES
    ]
    latent_by_run = {
        row["id"]: set(json.loads(row["latent_atom_ids"] or "[]"))
        for row in runs
    }
    latent_citation_count = 0
    for row in suggestions:
        cited = set(json.loads(row["cited_atom_ids"] or "[]"))
        if cited.intersection(latent_by_run.get(row["run_id"], set())):
            latent_citation_count += 1

    runs_count = len(runs)
    suggestions_count = len(suggestions)
    metrics = {
        "runs_count": runs_count,
        "suggestions_count": suggestions_count,
        "feedback_count": len(feedback),
        "positive_feedback_count": len(positive_feedback),
        "runs_with_feedback": len(feedback_run_ids.intersection(run_ids)),
        "runs_with_feedback_rate": _ratio(len(feedback_run_ids.intersection(run_ids)), runs_count),
        "positive_feedback_per_run": _ratio(len(positive_feedback), runs_count),
        "suggestions_per_run": _ratio(suggestions_count, runs_count),
        "latent_citation_count": latent_citation_count,
        "latent_citation_rate": _ratio(latent_citation_count, suggestions_count),
    }
    if runs_count == 0:
        verdict = "needs_data"
    elif metrics["positive_feedback_per_run"] >= 0.25:
        verdict = "pass"
    else:
        verdict = "fail"
    return ValidationResult(
        name="Inspire Validator",
        verdict=verdict,
        metrics=metrics,
        markdown=_render_inspire_markdown(verdict, metrics),
    )


def validate_report(
    store: MemoryStore,
    *,
    scout_eval_path: str | Path | None = None,
) -> ValidationResult:
    sections = []
    verdicts = []
    if scout_eval_path is not None:
        scout = validate_scout(scout_eval_path)
        sections.append(scout.markdown)
        verdicts.append(scout.verdict)
    notes = validate_notes(store)
    inspire = validate_inspire(store)
    sections.extend([notes.markdown, inspire.markdown])
    verdicts.extend([notes.verdict, inspire.verdict])
    verdict = _combine_verdicts(verdicts)
    metrics = {
        "section_verdicts": verdicts,
        "sections": len(sections),
    }
    markdown = "\n\n".join(
        [
            "# Sporepath Validation Report",
            f"- Verdict: `{verdict}`",
            "",
            *sections,
        ]
    )
    return ValidationResult("Sporepath Validation Report", verdict, metrics, markdown)


def write_validation_result(result: ValidationResult, out_path: str | Path | None) -> Path | None:
    if out_path is None:
        return None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.markdown, encoding="utf-8")
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _combine_verdicts(verdicts: Iterable[str]) -> str:
    values = list(verdicts)
    if "fail" in values:
        return "fail"
    if not values or "needs_data" in values:
        return "needs_data"
    return "pass"


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _render_scout_markdown(path: Path, verdict: str, metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Scout Validator",
            "",
            f"- Eval sheet: `{path}`",
            f"- Verdict: `{verdict}`",
            f"- Cases: {metrics['scored_cases']}/{metrics['total_cases']} scored",
            f"- Minimum scored cases: {metrics['minimum_scored_cases']}",
            f"- Pass rate: {_pct(metrics['pass_rate'])}",
            f"- Handoff sufficient: {_pct(metrics['handoff_sufficient_rate'])}",
            f"- Parse errors: {metrics['parse_error_count']} ({_pct(metrics['parse_error_rate'])})",
            f"- Duplicate rate: {_pct(metrics['duplicate_rate'])}",
            f"- Tool noise retained: {_pct(metrics['tool_noise_retained_rate'])}",
            f"- False negatives: {metrics['false_negative_count']} ({_pct(metrics['false_negative_rate'])})",
            "",
            "Targets: parse errors <= 3%, duplicates <= 10%, tool noise retained <= 5%, false negatives <= 15%, handoff sufficient >= 75%.",
        ]
    )


def _render_notes_markdown(verdict: str, metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Notes Validator",
            "",
            f"- Verdict: `{verdict}`",
            f"- Atoms: {metrics['atoms_count']}",
            f"- Notes: {metrics['notes_count']}",
            f"- Notes with sources: {metrics['notes_with_sources']} ({_pct(metrics['notes_with_sources_rate'])})",
            f"- Empty notes: {metrics['empty_note_count']} ({_pct(metrics['empty_note_rate'])})",
            f"- Notes with missing source atoms: {metrics['missing_source_note_count']} ({_pct(metrics['missing_source_note_rate'])})",
            f"- Duplicate titles: {metrics['duplicate_title_count']} ({_pct(metrics['duplicate_title_rate'])})",
            "",
            "Human check still required: readability, question-vs-conclusion mistakes, and whether the note deserves to stay in Obsidian.",
        ]
    )


def _render_inspire_markdown(verdict: str, metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Inspire Validator",
            "",
            f"- Verdict: `{verdict}`",
            f"- Runs: {metrics['runs_count']}",
            f"- Suggestions: {metrics['suggestions_count']}",
            f"- Feedback: {metrics['feedback_count']}",
            f"- Positive feedback: {metrics['positive_feedback_count']}",
            f"- Runs with feedback: {metrics['runs_with_feedback']} ({_pct(metrics['runs_with_feedback_rate'])})",
            f"- Positive feedback per run: {_pct(metrics['positive_feedback_per_run'])}",
            f"- Latent citation rate: {_pct(metrics['latent_citation_rate'])}",
            "",
            "Target: at least 25% positive feedback per inspire run. No runs means this validator needs real usage data.",
        ]
    )


def _pct(value: float) -> str:
    return f"{value:.1%}"
