from __future__ import annotations

from datetime import date
from typing import Any

from decisiontrail.assumptions import add_assumption_evidence_ref, normalize_assumptions, remove_evidence_ref_from_assumptions
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


def evidence_items(record: DecisionRecord) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
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


def normalize_evidence_item(value: Any, *, default_added_on: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    evidence_id = str(value.get("id", "") or "").strip()
    title = str(value.get("title", "") or "").strip()
    evidence_type = str(value.get("type", "") or "url").strip()
    ref = str(value.get("ref", "") or "").strip()
    note = str(value.get("note", "") or "").strip()
    added_on = str(value.get("added_on", "") or "").strip()
    links = normalize_evidence_links(value.get("links"))
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
    item: dict[str, Any] = {
        "title": title,
        "type": evidence_type,
        "ref": ref,
        "note": note,
        "added_on": added_on,
    }
    if evidence_id:
        item["id"] = evidence_id
    if links:
        item["links"] = links
    return item


def normalize_evidence_links(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    links: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        link_type = str(item.get("type", "") or "").strip()
        target = str(item.get("target", "") or "").strip()
        if link_type in {"assumption", "metric"} and target:
            links.append({"type": link_type, "target": target})
    return links


def next_evidence_id(record: DecisionRecord) -> str:
    highest = 0
    for item in evidence_items(record):
        evidence_id = str(item.get("id", "") or "").strip()
        if not evidence_id.startswith("EVD-"):
            continue
        try:
            highest = max(highest, int(evidence_id.removeprefix("EVD-")))
        except ValueError:
            continue
    return f"EVD-{highest + 1:03d}"


def append_evidence(
    record: DecisionRecord,
    *,
    title: str,
    evidence_type: str,
    ref: str = "",
    note: str = "",
    added_on: str = "",
    evidence_id: str = "",
    assumption_index: int | None = None,
    metric_name: str = "",
) -> dict[str, Any]:
    evidence_id = evidence_id.strip() or next_evidence_id(record)
    existing_ids = {str(item.get("id", "") or "").strip() for item in evidence_items(record)}
    if evidence_id in existing_ids:
        raise ValueError(f"Evidence id already exists: {evidence_id}.")

    links = []
    if assumption_index is not None:
        assumptions = normalize_assumptions(record.assumptions)
        if assumption_index < 0 or assumption_index >= len(assumptions):
            raise IndexError("Assumption not found.")
        links.append({"type": "assumption", "target": str(assumption_index)})
    if metric_name.strip():
        links.append({"type": "metric", "target": metric_name.strip()})

    item = normalize_evidence_item(
        {
            "id": evidence_id,
            "title": title,
            "type": evidence_type,
            "ref": ref,
            "note": note,
            "added_on": added_on,
            "links": links,
        }
    )
    record.metadata["evidence"] = [*evidence_items(record), item]
    if assumption_index is not None:
        add_assumption_evidence_ref(record, assumption_index, evidence_id)
    return item


def remove_evidence_at(record: DecisionRecord, index: int) -> dict[str, Any]:
    items = evidence_items(record)
    try:
        removed = items.pop(index)
    except IndexError as error:
        raise IndexError("Evidence index is out of range.") from error
    record.metadata["evidence"] = items
    evidence_id = str(removed.get("id", "") or "").strip()
    if evidence_id:
        remove_evidence_ref_from_assumptions(record, evidence_id)
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
