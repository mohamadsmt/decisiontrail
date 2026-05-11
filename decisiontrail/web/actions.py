from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from decisiontrail.models import DecisionRecord
from decisiontrail.relationships import backlinks, children_of, normalize_related_decisions, relation_to_metadata
from decisiontrail.web.forms import VALID_ASSUMPTION_STATUSES


@dataclass(frozen=True)
class DeleteBlockers:
    children: list[DecisionRecord]
    incoming_links: list

    @property
    def has_blockers(self) -> bool:
        return bool(self.children or self.incoming_links)


def normalize_assumption(value) -> dict[str, str]:
    if isinstance(value, dict):
        text = str(value.get("text", "") or "").strip()
        status = str(value.get("status", "") or "unvalidated").strip()
        note = str(value.get("note", "") or "").strip()
        reviewed_on = str(value.get("reviewed_on", "") or "").strip()
    else:
        text = str(value).strip()
        status = "unvalidated"
        note = ""
        reviewed_on = ""
    if status not in VALID_ASSUMPTION_STATUSES:
        status = "unvalidated"
    result = {"text": text, "status": status, "note": note, "reviewed_on": reviewed_on}
    return result


def update_assumption_status(
    record: DecisionRecord,
    index: int,
    status: str,
    note: str = "",
    reviewed_on: str | None = None,
) -> None:
    if status not in VALID_ASSUMPTION_STATUSES:
        raise ValueError("Unsupported assumption status.")
    assumptions = [normalize_assumption(item) for item in record.assumptions]
    if index < 0 or index >= len(assumptions):
        raise IndexError("Assumption not found.")
    assumptions[index]["status"] = status
    assumptions[index]["note"] = note.strip()
    assumptions[index]["reviewed_on"] = reviewed_on or date.today().isoformat()
    record.metadata["assumptions"] = assumptions


def remove_relation_at(record: DecisionRecord, index: int) -> None:
    relations = normalize_related_decisions(record)
    if index < 0 or index >= len(relations):
        raise IndexError("Relation not found.")
    relations.pop(index)
    record.metadata["related_decisions"] = [relation_to_metadata(relation) for relation in relations]


def delete_blockers(record: DecisionRecord, records: list[DecisionRecord]) -> DeleteBlockers:
    return DeleteBlockers(
        children=children_of(records, record.id),
        incoming_links=backlinks(records, record.id),
    )
