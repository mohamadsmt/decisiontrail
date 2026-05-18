from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from decisiontrail.assumptions import VALID_ASSUMPTION_STATUSES, parse_evidence_refs, validate_assumption_dates
from decisiontrail.models import DecisionRecord, VALID_DECISION_TYPES, VALID_DIRECTIONS, VALID_RELATION_TYPES, VALID_STATUSES
from decisiontrail.relationships import normalize_related_decisions, parse_relation_lines, relation_to_metadata


VALID_LANGUAGE_OPTIONS = [
    {"code": "en", "label": "English"},
    {"code": "fa", "label": "Persian"},
]
VALID_LANGUAGE_CODES = [option["code"] for option in VALID_LANGUAGE_OPTIONS]


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


def parse_assumptions(value: str) -> list[dict[str, Any]]:
    assumptions: list[dict[str, Any]] = []
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
            assumption.update(parse_assumption_metadata(note.strip()))
        assumptions.append(assumption)
    return assumptions


def parse_assumption_metadata(value: str) -> dict[str, Any]:
    if "=" not in value:
        return {"note": value}

    metadata: dict[str, Any] = {}
    note_parts: list[str] = []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        key, separator, raw_value = part.partition("=")
        if not separator:
            note_parts.append(part)
            continue
        key = key.strip()
        text = raw_value.strip()
        if key == "note":
            if text:
                metadata["note"] = text
        elif key == "owner":
            if text:
                metadata["owner"] = text
        elif key == "due_on":
            if text:
                metadata["due_on"] = text
        elif key == "signal":
            if text:
                metadata["signal"] = text
        elif key in {"evidence", "evidence_refs"}:
            refs = parse_evidence_refs(text)
            if refs:
                metadata["evidence_refs"] = refs
        else:
            note_parts.append(part)
    if note_parts and "note" not in metadata:
        metadata["note"] = "; ".join(note_parts)
    return metadata


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
    for assumption in parse_assumptions(data.assumptions):
        try:
            validate_assumption_dates(assumption)
        except ValueError as error:
            errors.append(str(error))
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
            owner = str(assumption.get("owner", "") or "").strip()
            due_on = str(assumption.get("due_on", "") or "").strip()
            signal = str(assumption.get("signal", "") or "").strip()
            evidence_refs = parse_evidence_refs(assumption.get("evidence_refs"))
        else:
            text = str(assumption).strip()
            status = "unvalidated"
            note = ""
            owner = ""
            due_on = ""
            signal = ""
            evidence_refs = []
        if not text:
            continue
        prefix = f"{status}: " if status != "unvalidated" or note else ""
        details = []
        if owner:
            details.append(f"owner={owner}")
        if due_on:
            details.append(f"due_on={due_on}")
        if signal:
            details.append(f"signal={signal}")
        if evidence_refs:
            details.append(f"evidence={','.join(evidence_refs)}")
        if details:
            if note:
                details.append(f"note={note}")
            suffix = " | " + "; ".join(details)
        else:
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
