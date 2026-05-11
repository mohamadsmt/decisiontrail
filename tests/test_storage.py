from __future__ import annotations

from datetime import date

from decisiontrail.config import load_config
from decisiontrail.storage import create_decision, load_decisions, next_decision_id, slugify, split_frontmatter


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
