from __future__ import annotations

from decisiontrail.config import load_config
from decisiontrail.relationships import (
    append_relation,
    backlinks,
    children_of,
    outgoing_relations,
    parse_relation_line,
    relation_to_metadata,
)
from decisiontrail.review import validate_record
from decisiontrail.storage import create_decision
from decisiontrail.web.actions import delete_blockers, remove_relation_at, update_assumption_status


def test_parse_relation_line_supports_type_target_and_note() -> None:
    relation = parse_relation_line("depends_on: DEC-2026-001 | Pricing context", source_id="DEC-2026-002")

    assert relation is not None
    assert relation.source_id == "DEC-2026-002"
    assert relation.target_id == "DEC-2026-001"
    assert relation.relation_type == "depends_on"
    assert relation.note == "Pricing context"


def test_children_and_backlinks_are_computed_from_records(tmp_path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent decision")
    related = create_decision(tmp_path, config, "Related decision")
    relation = parse_relation_line(f"informs: {related.id} | Context")
    assert relation is not None
    child = create_decision(
        tmp_path,
        config,
        "Child decision",
        parent_id=parent.id,
        related_decisions=[relation_to_metadata(relation)],
    )

    records = [parent, related, child]

    assert children_of(records, parent.id) == [child]
    assert outgoing_relations(child)[0].target_id == related.id
    assert backlinks(records, related.id)[0].source_id == child.id


def test_append_relation_deduplicates_exact_relationship(tmp_path) -> None:
    config = load_config(tmp_path)
    source = create_decision(tmp_path, config, "Source")
    target = create_decision(tmp_path, config, "Target")
    relation = parse_relation_line(f"blocks: {target.id} | Must land first", source_id=source.id)
    assert relation is not None

    append_relation(source, relation)
    append_relation(source, relation)

    assert source.related_decisions == [{"id": target.id, "type": "blocks", "note": "Must land first"}]


def test_validate_record_rejects_bad_relationship_references(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Bad links",
        related_decisions=[{"id": "DEC-2026-999", "type": "unknown"}],
    )

    issues = validate_record(record, records=[record])

    assert any("unsupported relation type" in issue for issue in issues)
    assert any("references unknown decision" in issue for issue in issues)


def test_validate_record_detects_parent_cycles(tmp_path) -> None:
    config = load_config(tmp_path)
    first = create_decision(tmp_path, config, "First")
    second = create_decision(tmp_path, config, "Second", parent_id=first.id)
    first.metadata["parent_id"] = second.id

    issues = validate_record(first, records=[first, second])

    assert any("parent chain contains a cycle" in issue for issue in issues)


def test_update_assumption_status_preserves_persian_text(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Assumption", assumptions=["کاربران fee کمتر می‌خواهند."])

    update_assumption_status(record, 0, "validated", note="Confirmed by survey", reviewed_on="2026-08-01")

    assert record.metadata["assumptions"] == [
        {
            "text": "کاربران fee کمتر می‌خواهند.",
            "status": "validated",
            "note": "Confirmed by survey",
            "reviewed_on": "2026-08-01",
        }
    ]


def test_remove_relation_at_and_delete_blockers(tmp_path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent")
    child = create_decision(tmp_path, config, "Child", parent_id=parent.id)
    source = create_decision(
        tmp_path,
        config,
        "Source",
        related_decisions=[{"id": parent.id, "type": "informs", "note": "Context"}],
    )

    blockers = delete_blockers(parent, [parent, child, source])

    assert blockers.children == [child]
    assert blockers.incoming_links[0].source_id == source.id

    remove_relation_at(source, 0)

    assert source.related_decisions == []
