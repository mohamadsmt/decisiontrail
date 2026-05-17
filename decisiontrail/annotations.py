from __future__ import annotations

from datetime import date
from typing import Any

from decisiontrail.models import DecisionRecord, VALID_EVIDENCE_TYPES


def parse_iso_date(value: str, *, field_name: str) -> str:
    value = value.strip()
    if not value:
        return date.today().isoformat()
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must use ISO format: YYYY-MM-DD.") from error
    return value


def evidence_items(record: DecisionRecord) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in record.evidence:
        normalized = normalize_evidence_item(item, default_added_on=False)
        if normalized:
            items.append(normalized)
    return items


def metric_updates(record: DecisionRecord) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in record.metric_updates:
        normalized = normalize_metric_update(item, default_measured_on=False)
        if normalized:
            items.append(normalized)
    return items


def normalize_evidence_item(value: Any, *, default_added_on: bool = True) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    title = str(value.get("title", "") or "").strip()
    evidence_type = str(value.get("type", "") or "url").strip()
    ref = str(value.get("ref", "") or "").strip()
    note = str(value.get("note", "") or "").strip()
    added_on = str(value.get("added_on", "") or "").strip()
    if evidence_type not in VALID_EVIDENCE_TYPES:
        raise ValueError(f"Evidence type must be one of: {', '.join(sorted(VALID_EVIDENCE_TYPES))}.")
    if not title:
        raise ValueError("Evidence title is required.")
    if evidence_type != "note" and not ref:
        raise ValueError("Evidence reference is required unless type is note.")
    if evidence_type == "note" and not (ref or note):
        raise ValueError("Note evidence requires a reference or note.")
    if default_added_on or added_on:
        added_on = parse_iso_date(added_on, field_name="added_on")
    return {
        "title": title,
        "type": evidence_type,
        "ref": ref,
        "note": note,
        "added_on": added_on,
    }


def append_evidence(
    record: DecisionRecord,
    *,
    title: str,
    evidence_type: str,
    ref: str = "",
    note: str = "",
    added_on: str = "",
) -> dict[str, str]:
    item = normalize_evidence_item(
        {"title": title, "type": evidence_type, "ref": ref, "note": note, "added_on": added_on}
    )
    record.metadata["evidence"] = [*evidence_items(record), item]
    return item


def remove_evidence_at(record: DecisionRecord, index: int) -> dict[str, str]:
    items = evidence_items(record)
    try:
        removed = items.pop(index)
    except IndexError as error:
        raise IndexError("Evidence index is out of range.") from error
    record.metadata["evidence"] = items
    return removed


def normalize_metric_update(value: Any, *, default_measured_on: bool = True) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    name = str(value.get("name", "") or "").strip()
    metric_value = str(value.get("value", "") or "").strip()
    measured_on = str(value.get("measured_on", "") or "").strip()
    note = str(value.get("note", "") or "").strip()
    if not name:
        raise ValueError("Metric name is required.")
    if not metric_value and not note:
        raise ValueError("Metric value or note is required.")
    if default_measured_on or measured_on:
        measured_on = parse_iso_date(measured_on, field_name="measured_on")
    return {
        "name": name,
        "value": metric_value,
        "measured_on": measured_on,
        "note": note,
    }


def append_metric_update(
    record: DecisionRecord,
    *,
    name: str,
    value: str = "",
    measured_on: str = "",
    note: str = "",
) -> dict[str, str]:
    item = normalize_metric_update({"name": name, "value": value, "measured_on": measured_on, "note": note})
    record.metadata["metric_updates"] = [*metric_updates(record), item]
    return item
