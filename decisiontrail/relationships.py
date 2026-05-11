from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from decisiontrail.models import DecisionRecord, VALID_RELATION_TYPES


@dataclass(frozen=True)
class DecisionRelation:
    source_id: str
    target_id: str
    relation_type: str
    note: str = ""


def relation_type_label(relation_type: str) -> str:
    return relation_type.replace("_", " ")


def normalize_relation(value: Any, source_id: str = "") -> DecisionRelation | None:
    if isinstance(value, DecisionRelation):
        return value
    if isinstance(value, dict):
        target_id = str(value.get("id", "") or value.get("target_id", "") or "").strip()
        relation_type = str(value.get("type", "") or "related_to").strip()
        note = str(value.get("note", "") or "").strip()
        if not target_id:
            return None
        return DecisionRelation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            note=note,
        )
    if isinstance(value, str):
        return parse_relation_line(value, source_id=source_id)
    return None


def relation_to_metadata(relation: DecisionRelation) -> dict[str, str]:
    data = {"id": relation.target_id, "type": relation.relation_type}
    if relation.note:
        data["note"] = relation.note
    return data


def normalize_related_decisions(record: DecisionRecord) -> list[DecisionRelation]:
    relations: list[DecisionRelation] = []
    for value in record.related_decisions:
        relation = normalize_relation(value, source_id=record.id)
        if relation:
            relations.append(relation)
    return relations


def parse_relation_line(line: str, source_id: str = "") -> DecisionRelation | None:
    text = line.strip()
    if not text:
        return None
    left, separator, note = text.partition("|")
    relation_part = left.strip()
    relation_note = note.strip() if separator else ""

    if ":" in relation_part:
        relation_type, target_id = relation_part.split(":", 1)
    else:
        relation_type, target_id = "related_to", relation_part

    target_id = target_id.strip()
    relation_type = relation_type.strip() or "related_to"
    if not target_id:
        return None
    return DecisionRelation(
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        note=relation_note,
    )


def parse_relation_lines(value: str, source_id: str = "") -> list[DecisionRelation]:
    relations = []
    for line in value.splitlines():
        relation = parse_relation_line(line, source_id=source_id)
        if relation:
            relations.append(relation)
    return relations


def parse_relation_args(values: list[str], source_id: str = "") -> list[DecisionRelation]:
    relations = []
    for value in values:
        relation = parse_relation_line(value, source_id=source_id)
        if relation:
            relations.append(relation)
    return relations


def children_of(records: list[DecisionRecord], parent_id: str) -> list[DecisionRecord]:
    return [record for record in records if record.parent_id == parent_id]


def outgoing_relations(record: DecisionRecord) -> list[DecisionRelation]:
    return normalize_related_decisions(record)


def backlinks(records: list[DecisionRecord], target_id: str) -> list[DecisionRelation]:
    links: list[DecisionRelation] = []
    for record in records:
        for relation in normalize_related_decisions(record):
            if relation.target_id == target_id:
                links.append(relation)
    return links


def parent_chain(record: DecisionRecord, records_by_id: dict[str, DecisionRecord]) -> list[str]:
    chain: list[str] = []
    seen = {record.id}
    current = record.parent_id
    while current:
        chain.append(current)
        if current in seen:
            break
        seen.add(current)
        parent = records_by_id.get(current)
        if not parent:
            break
        current = parent.parent_id
    return chain


def has_parent_cycle(record: DecisionRecord, records_by_id: dict[str, DecisionRecord]) -> bool:
    seen = {record.id}
    current = record.parent_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        parent = records_by_id.get(current)
        if not parent:
            return False
        current = parent.parent_id
    return False


def relation_errors(record: DecisionRecord, records: list[DecisionRecord] | None = None) -> list[str]:
    issues: list[str] = []
    records_by_id = {item.id: item for item in records or [] if item.id}

    if record.parent_id:
        if record.parent_id == record.id:
            issues.append(f"{record.id}: parent_id cannot reference itself")
        if records is not None and record.parent_id not in records_by_id:
            issues.append(f"{record.id}: parent_id references unknown decision '{record.parent_id}'")
        if records is not None and has_parent_cycle(record, records_by_id):
            issues.append(f"{record.id}: parent chain contains a cycle")

    for relation in normalize_related_decisions(record):
        if relation.relation_type not in VALID_RELATION_TYPES:
            issues.append(f"{record.id}: unsupported relation type '{relation.relation_type}'")
        if relation.target_id == record.id:
            issues.append(f"{record.id}: related_decisions cannot reference itself")
        if records is not None and relation.target_id not in records_by_id:
            issues.append(f"{record.id}: related_decisions references unknown decision '{relation.target_id}'")
    return issues


def append_relation(record: DecisionRecord, relation: DecisionRelation) -> None:
    existing = normalize_related_decisions(record)
    for item in existing:
        if item.target_id == relation.target_id and item.relation_type == relation.relation_type and item.note == relation.note:
            return
    existing.append(relation)
    record.metadata["related_decisions"] = [relation_to_metadata(item) for item in existing]
