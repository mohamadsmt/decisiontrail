from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from decisiontrail.models import DecisionRecord, VALID_DECISION_TYPES, VALID_DIRECTIONS, VALID_RELATION_TYPES, VALID_STATUSES
from decisiontrail.relationships import normalize_related_decisions, parse_relation_lines, relation_to_metadata


VALID_ASSUMPTION_STATUSES = {"unvalidated", "pending", "validated", "invalidated"}


@dataclass(frozen=True)
class DecisionFormData:
    title: str = ""
    decision_type: str = "general"
    owner: str = ""
    status: str = "proposed"
    context: str = ""
    options: str = ""
    decision: str = ""
    rationale: str = ""
    assumptions: str = ""
    success_metrics: str = ""
    revisit_on: str = ""
    language: str = "en"
    direction: str = "auto"
    tags: str = ""
    parent_id: str = ""
    related_decisions: str = ""
    body: str = ""


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def parse_assumptions(value: str) -> list[dict[str, str]]:
    assumptions: list[dict[str, str]] = []
    for line in split_lines(value):
        content, separator, note = line.partition("|")
        left = content.strip()
        status = "unvalidated"
        text = left
        if ":" in left:
            possible_status, possible_text = left.split(":", 1)
            if possible_status.strip() in VALID_ASSUMPTION_STATUSES:
                status = possible_status.strip()
                text = possible_text.strip()
        if not text:
            continue
        assumption = {"text": text, "status": status}
        if separator and note.strip():
            assumption["note"] = note.strip()
        assumptions.append(assumption)
    return assumptions


def validate_decision_form(
    data: DecisionFormData,
    known_ids: set[str] | None = None,
    current_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not data.title.strip():
        errors.append("Title is required.")
    if data.status not in VALID_STATUSES:
        errors.append(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}.")
    if data.decision_type not in VALID_DECISION_TYPES:
        errors.append(f"Decision type must be one of: {', '.join(sorted(VALID_DECISION_TYPES))}.")
    if data.direction not in VALID_DIRECTIONS:
        errors.append("Direction must be auto, ltr, or rtl.")
    if data.revisit_on.strip():
        try:
            date.fromisoformat(data.revisit_on.strip())
        except ValueError:
            errors.append("Revisit date must use ISO format: YYYY-MM-DD.")
    if data.parent_id.strip() and current_id and data.parent_id.strip() == current_id:
        errors.append("A decision cannot be its own parent.")
    if known_ids is not None and data.parent_id.strip() and data.parent_id.strip() not in known_ids:
        errors.append(f"Parent decision does not exist: {data.parent_id.strip()}.")
    for relation in parse_relation_lines(data.related_decisions):
        if relation.relation_type not in VALID_RELATION_TYPES:
            errors.append(f"Unsupported relation type: {relation.relation_type}.")
        if current_id and relation.target_id == current_id:
            errors.append("A decision cannot relate to itself.")
        if known_ids is not None and relation.target_id not in known_ids:
            errors.append(f"Related decision does not exist: {relation.target_id}.")
    return errors


def form_to_metadata_updates(data: DecisionFormData) -> dict[str, Any]:
    return {
        "title": data.title.strip(),
        "decision_type": data.decision_type,
        "status": data.status,
        "owner": data.owner.strip(),
        "context": data.context.strip(),
        "options": split_lines(data.options),
        "decision": data.decision.strip(),
        "rationale": split_lines(data.rationale),
        "assumptions": parse_assumptions(data.assumptions),
        "success_metrics": split_lines(data.success_metrics),
        "revisit_on": data.revisit_on.strip(),
        "language": data.language.strip() or "en",
        "direction": data.direction,
        "tags": split_lines(data.tags),
        "parent_id": data.parent_id.strip(),
        "related_decisions": [relation_to_metadata(relation) for relation in parse_relation_lines(data.related_decisions)],
    }


def form_to_create_kwargs(data: DecisionFormData) -> dict[str, Any]:
    updates = form_to_metadata_updates(data)
    updates.pop("title", None)
    return updates


def assumptions_to_text(record: DecisionRecord) -> str:
    lines: list[str] = []
    for assumption in record.assumptions:
        if isinstance(assumption, dict):
            text = str(assumption.get("text", "")).strip()
            status = str(assumption.get("status", "") or "unvalidated").strip()
            note = str(assumption.get("note", "") or "").strip()
        else:
            text = str(assumption).strip()
            status = "unvalidated"
            note = ""
        if not text:
            continue
        prefix = f"{status}: " if status != "unvalidated" or note else ""
        suffix = f" | {note}" if note else ""
        lines.append(f"{prefix}{text}{suffix}")
    return "\n".join(lines)


def related_decisions_to_text(record: DecisionRecord) -> str:
    lines: list[str] = []
    for relation in normalize_related_decisions(record):
        note = f" | {relation.note}" if relation.note else ""
        lines.append(f"{relation.relation_type}: {relation.target_id}{note}")
    return "\n".join(lines)


def record_to_form_data(record: DecisionRecord) -> DecisionFormData:
    return DecisionFormData(
        title=record.title,
        decision_type=record.decision_type,
        owner=record.owner,
        status=record.status,
        context=str(record.metadata.get("context", "") or ""),
        options="\n".join(str(item) for item in record.options),
        decision=str(record.metadata.get("decision", "") or ""),
        rationale="\n".join(str(item) for item in record.rationale),
        assumptions=assumptions_to_text(record),
        success_metrics="\n".join(str(item) for item in record.success_metrics),
        revisit_on=str(record.metadata.get("revisit_on", "") or ""),
        language=record.language,
        direction=record.direction,
        tags="\n".join(str(item) for item in record.tags),
        parent_id=record.parent_id,
        related_decisions=related_decisions_to_text(record),
        body=record.body,
    )
