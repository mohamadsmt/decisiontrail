from __future__ import annotations

from datetime import date

from decisiontrail.config import load_config
from decisiontrail.export import export_html
from decisiontrail.parser import parse_meeting_notes
from decisiontrail.storage import create_decision


def test_parse_meeting_notes_extracts_decision_drafts(tmp_path) -> None:
    note = tmp_path / "meeting.md"
    note.write_text(
        """# Weekly

## Decision: Change onboarding KYC flow
Option: Keep current flow
Option: Move risk checks earlier
Assumption: Users will tolerate one extra verification step.
Metric: activation_rate
""",
        encoding="utf-8",
    )

    drafts = parse_meeting_notes(note)

    assert len(drafts) == 1
    assert drafts[0].title == "Change onboarding KYC flow"
    assert drafts[0].options == ["Keep current flow", "Move risk checks earlier"]
    assert drafts[0].success_metrics == ["activation_rate"]


def test_parse_meeting_notes_supports_persian_decision_marker(tmp_path) -> None:
    note = tmp_path / "meeting-fa.md"
    note.write_text(
        """# جلسه

- تصمیم: تغییر مسیر پرداخت
فرض: کاربران مسیر کوتاه‌تر را ترجیح می‌دهند.
معیار: conversion_rate
""",
        encoding="utf-8",
    )

    drafts = parse_meeting_notes(note)

    assert drafts[0].title == "تغییر مسیر پرداخت"
    assert drafts[0].assumptions == ["کاربران مسیر کوتاه‌تر را ترجیح می‌دهند."]


def test_export_html_uses_rtl_metadata_and_utf8_content(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "تصمیم فارسی",
        created_on=date(2026, 5, 11),
        context="متن فارسی با metric انگلیسی.",
        decision="ادامه مسیر",
        language="fa",
        direction="rtl",
    )

    pages = export_html([record], tmp_path / "site", config)
    decision_page = next(path for path in pages if path.name != "index.html")
    html = decision_page.read_text(encoding="utf-8")

    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert "تصمیم فارسی" in html
    assert "margin-inline" in html


def test_export_html_renders_tags_and_static_tag_filter(tmp_path) -> None:
    config = load_config(tmp_path)
    pricing = create_decision(tmp_path, config, "Pricing decision", tags=["Pricing", "Growth"])
    create_decision(tmp_path, config, "Operations decision", tags=["Operations"])

    pages = export_html([pricing], tmp_path / "single-site", config)
    single_index = (tmp_path / "single-site" / "index.html").read_text(encoding="utf-8")
    detail_html = next(path for path in pages if path.name != "index.html").read_text(encoding="utf-8")

    assert 'data-tag-filter' in single_index
    assert '<option value="pricing">Pricing</option>' in single_index
    assert '<span class="tag-pill">Pricing</span>' in single_index
    assert '<span class="tag-pill">Growth</span>' in detail_html

    all_pages = export_html([pricing, create_decision(tmp_path, config, "Support decision", tags=["Operations"])], tmp_path / "site-all", config)
    all_index = (tmp_path / "site-all" / "index.html").read_text(encoding="utf-8")
    assert 'JSON.parse(card.dataset.tagKeys || "[]")' in all_index
    assert "data-tag-keys=" in all_index
    assert "pricing" in all_index
    assert "growth" in all_index
    assert len(all_pages) == 3


def test_export_html_renders_relationships_and_backlinks(tmp_path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent decision")
    target = create_decision(tmp_path, config, "Target decision")
    child = create_decision(
        tmp_path,
        config,
        "Child decision",
        parent_id=parent.id,
        related_decisions=[{"id": target.id, "type": "informs", "note": "Metric context"}],
    )

    pages = export_html([parent, target, child], tmp_path / "site", config)
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    child_page = next(path for path in pages if child.id in path.name).read_text(encoding="utf-8")
    target_page = next(path for path in pages if target.id in path.name).read_text(encoding="utf-8")

    assert "Children" in index_html
    assert parent.id in child_page
    assert "informs" in child_page
    assert "Metric context" in child_page
    assert "Linked from" in target_page
    assert child.id in target_page
