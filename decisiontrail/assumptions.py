from __future__ import annotations

from datetime import date
from typing import Any


VALID_ASSUMPTION_STATUSES = {"unvalidated", "pending", "validated", "invalidated"}


def parse_evidence_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
        return [item.strip() for item in raw_items if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_assumption(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        text = str(value.get("text", "") or "").strip()
        status = str(value.get("status", "") or "unvalidated").strip()
        note = str(value.get("note", "") or "").strip()
        reviewed_on = str(value.get("reviewed_on", "") or "").strip()
        owner = str(value.get("owner", "") or "").strip()
        due_on = str(value.get("due_on", "") or "").strip()
        signal = str(value.get("signal", "") or "").strip()
        evidence_refs = parse_evidence_refs(value.get("evidence_refs"))
    else:
        text = str(value).strip()
        status = "unvalidated"
        note = ""
        reviewed_on = ""
        owner = ""
        due_on = ""
        signal = ""
        evidence_refs = []

    if status not in VALID_ASSUMPTION_STATUSES:
        status = "unvalidated"

    result: dict[str, Any] = {"text": text, "status": status}
    if owner:
        result["owner"] = owner
    if due_on:
        result["due_on"] = due_on
    if signal:
        result["signal"] = signal
    if evidence_refs:
        result["evidence_refs"] = evidence_refs
    if note:
        result["note"] = note
    if reviewed_on:
        result["reviewed_on"] = reviewed_on
    return result


def normalize_assumptions(values: list[Any]) -> list[dict[str, Any]]:
    return [item for item in (normalize_assumption(value) for value in values) if item.get("text")]


def validate_assumption_dates(assumption: dict[str, Any]) -> None:
    for field_name in ("due_on", "reviewed_on"):
        value = str(assumption.get(field_name, "") or "").strip()
        if not value:
            continue
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{field_name} must use ISO format: YYYY-MM-DD.") from error


def update_assumption_status(
    record,
    index: int,
    status: str,
    *,
    note: str = "",
    reviewed_on: str | None = None,
    owner: str | None = None,
    due_on: str | None = None,
    signal: str | None = None,
    evidence_refs: Any = None,
) -> None:
    if status not in VALID_ASSUMPTION_STATUSES:
        raise ValueError("Unsupported assumption status.")
    assumptions = normalize_assumptions(record.assumptions)
    if index < 0 or index >= len(assumptions):
        raise IndexError("Assumption not found.")

    assumption = assumptions[index]
    assumption["status"] = status
    _set_optional(assumption, "note", note)
    _set_optional(assumption, "reviewed_on", reviewed_on or date.today().isoformat())
    if owner is not None:
        _set_optional(assumption, "owner", owner)
    if due_on is not None:
        _set_optional(assumption, "due_on", due_on)
    if signal is not None:
        _set_optional(assumption, "signal", signal)
    if evidence_refs is not None:
        refs = parse_evidence_refs(evidence_refs)
        if refs:
            assumption["evidence_refs"] = refs
        else:
            assumption.pop("evidence_refs", None)
    validate_assumption_dates(assumption)
    record.metadata["assumptions"] = assumptions


def add_assumption_evidence_ref(record, index: int, evidence_id: str) -> None:
    assumptions = normalize_assumptions(record.assumptions)
    if index < 0 or index >= len(assumptions):
        raise IndexError("Assumption not found.")
    refs = parse_evidence_refs(assumptions[index].get("evidence_refs"))
    if evidence_id not in refs:
        refs.append(evidence_id)
    assumptions[index]["evidence_refs"] = refs
    record.metadata["assumptions"] = assumptions


def remove_evidence_ref_from_assumptions(record, evidence_id: str) -> None:
    assumptions = normalize_assumptions(record.assumptions)
    changed = False
    for assumption in assumptions:
        refs = parse_evidence_refs(assumption.get("evidence_refs"))
        if evidence_id not in refs:
            continue
        assumption["evidence_refs"] = [ref for ref in refs if ref != evidence_id]
        if not assumption["evidence_refs"]:
            assumption.pop("evidence_refs", None)
        changed = True
    if changed:
        record.metadata["assumptions"] = assumptions


def _set_optional(target: dict[str, Any], key: str, value: str | None) -> None:
    text = str(value or "").strip()
    if text:
        target[key] = text
    else:
        target.pop(key, None)
