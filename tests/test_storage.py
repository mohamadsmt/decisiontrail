from __future__ import annotations

from datetime import date

from decisiontrail.config import load_config
from decisiontrail.storage import (
    copy_decision_record,
    create_decision,
    delete_versioned_decision,
    load_decision,
    load_decisions,
    load_history_snapshot,
    next_decision_id,
    read_history_events,
    slugify,
    split_frontmatter,
    version_snapshot_path,
    write_versioned_decision,
)


def test_split_frontmatter_preserves_persian_text() -> None:
    metadata, body = split_frontmatter("---\ntitle: تصمیم فارسی\nlanguage: fa\n---\nمتن فارسی\n")

    assert metadata["title"] == "تصمیم فارسی"
    assert metadata["language"] == "fa"
    assert body == "متن فارسی\n"


def test_slugify_uses_ascii_fallback_for_persian_title() -> None:
    assert slugify("Launch Tiered Pricing!") == "launch-tiered-pricing"
    assert slugify("تصمیم فارسی") == "decision"


def test_create_decision_generates_stable_ids(tmp_path) -> None:
    config = load_config(tmp_path)
    first = create_decision(tmp_path, config, "First decision", created_on=date(2026, 5, 11))
    second = create_decision(tmp_path, config, "Second decision", created_on=date(2026, 5, 12))

    assert first.id == "DEC-2026-001"
    assert second.id == "DEC-2026-002"
    assert next_decision_id(tmp_path, config, 2026) == "DEC-2026-003"


def test_load_decisions_reads_markdown_records(tmp_path) -> None:
    config = load_config(tmp_path)
    create_decision(tmp_path, config, "Launch pricing", owner="Product")

    records = load_decisions(tmp_path, config)

    assert len(records) == 1
    assert records[0].title == "Launch pricing"
    assert records[0].owner == "Product"


def test_create_decision_persists_relationship_metadata(tmp_path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent")
    target = create_decision(tmp_path, config, "Target")
    child = create_decision(
        tmp_path,
        config,
        "Child",
        parent_id=parent.id,
        related_decisions=[{"id": target.id, "type": "depends_on", "note": "Required first"}],
    )

    assert child.parent_id == parent.id
    assert child.related_decisions == [{"id": target.id, "type": "depends_on", "note": "Required first"}]


def test_create_decision_initializes_version_metadata_and_history_snapshot(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Versioned decision", owner="Product")

    assert record.version == 1
    assert record.created_at
    assert record.updated_at == record.created_at
    assert version_snapshot_path(tmp_path, config, record.id, 1).exists()

    events = read_history_events(tmp_path, config, record.id)
    assert events == [
        {
            "version": 1,
            "previous_version": None,
            "changed_at": record.updated_at,
            "source": "storage",
            "action": "created",
            "changed_fields": ["created"],
            "snapshot": f".decisiontrail/history/{record.id}/v0001.md",
        }
    ]


def test_versioned_write_creates_next_snapshot_and_skips_noop(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Editable decision")

    previous = copy_decision_record(record)
    record.metadata["owner"] = "Product"
    result = write_versioned_decision(tmp_path, config, previous, record, source="test", action="edited")

    assert result.changed is True
    assert result.version == 2
    updated = load_decision(tmp_path, config, record.id)
    assert updated.version == 2
    assert updated.created_at == previous.created_at
    assert updated.updated_at
    assert load_history_snapshot(tmp_path, config, record.id, 1).owner == ""
    assert load_history_snapshot(tmp_path, config, record.id, 2).owner == "Product"
    assert read_history_events(tmp_path, config, record.id)[-1]["changed_fields"] == ["owner"]

    unchanged = load_decision(tmp_path, config, record.id)
    no_op = write_versioned_decision(
        tmp_path,
        config,
        copy_decision_record(unchanged),
        unchanged,
        source="test",
        action="edited",
    )

    assert no_op.changed is False
    assert no_op.version == 2
    assert len(read_history_events(tmp_path, config, record.id)) == 2


def test_existing_record_without_version_gets_lazy_baseline_on_first_change(tmp_path) -> None:
    config = load_config(tmp_path)
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    path = decisions_dir / "DEC-2026-001-legacy.md"
    path.write_text(
        "---\n"
        "id: DEC-2026-001\n"
        "title: Legacy decision\n"
        "status: proposed\n"
        "date: 2026-05-11\n"
        "---\n"
        "# Legacy decision\n",
        encoding="utf-8",
    )
    record = load_decision(tmp_path, config, "DEC-2026-001")
    previous = copy_decision_record(record)
    record.metadata["status"] = "accepted"

    result = write_versioned_decision(tmp_path, config, previous, record, source="test", action="status_updated")

    assert result.version == 2
    assert load_history_snapshot(tmp_path, config, record.id, 1).status == "proposed"
    assert load_history_snapshot(tmp_path, config, record.id, 2).status == "accepted"
    assert [event["action"] for event in read_history_events(tmp_path, config, record.id)] == [
        "baseline",
        "status_updated",
    ]


def test_delete_versioned_decision_removes_record_and_keeps_final_snapshot(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Delete me")

    result = delete_versioned_decision(tmp_path, config, record, source="test")

    assert result.changed is True
    assert result.version == 2
    assert not record.path.exists()
    assert load_history_snapshot(tmp_path, config, record.id, 2).title == "Delete me"
    assert read_history_events(tmp_path, config, record.id)[-1]["action"] == "deleted"
