from __future__ import annotations

from dataclasses import dataclass

from decisiontrail.assumptions import normalize_assumption, update_assumption_status
from decisiontrail.models import DecisionRecord
from decisiontrail.relationships import backlinks, children_of, normalize_related_decisions, relation_to_metadata


@dataclass(frozen=True)
class DeleteBlockers:
    children: list[DecisionRecord]
    incoming_links: list

    @property
    def has_blockers(self) -> bool:
        return bool(self.children or self.incoming_links)


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
