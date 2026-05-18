from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from decisiontrail.config import load_config
from decisiontrail.storage import create_decision, load_decision, load_decisions, read_history_events
from decisiontrail.web.app import create_web_app


def test_dashboard_renders_existing_records_and_summaries(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    create_decision(
        tmp_path,
        config,
        "Launch pricing",
        owner="Product",
        assumptions=["Merchants accept tiers"],
        revisit_on="2026-01-01",
    )
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert "Decision dashboard" in response.text
    assert "Launch pricing" in response.text
    assert "Unvalidated assumptions" in response.text
    assert "<th>Language</th>" not in response.text


def test_ui_creates_english_decision(tmp_path: Path) -> None:
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        "/decisions",
        data={
            "title": "Launch partner pricing",
            "owner": "Product",
            "status": "accepted",
            "context": "Partners need clearer pricing.",
            "options": "Keep current pricing\nLaunch partner tier",
            "decision": "Launch partner tier",
            "rationale": "Better margin control",
            "assumptions": "Partners understand tiered pricing.",
            "success_metrics": "gross_margin\npartner_retention",
            "revisit_on": "2026-08-01",
            "language": "en",
            "direction": "auto",
            "tags": "pricing\npartners",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    records = load_decisions(tmp_path, load_config(tmp_path))
    assert len(records) == 1
    assert records[0].title == "Launch partner pricing"
    assert records[0].assumptions == [{"text": "Partners understand tiered pricing.", "status": "unvalidated"}]


def test_new_decision_form_renders_empty_state(tmp_path: Path) -> None:
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/decisions/new")

    assert response.status_code == 200
    assert "Add decision" in response.text
    assert 'id="revisit_on" name="revisit_on" type="date" value="" dir="ltr"' in response.text
    assert '<select id="language" name="language">' in response.text
    assert '<option value="en" selected>English</option>' in response.text
    assert '<option value="fa" >Persian</option>' in response.text
    assert 'dir="auto"' in response.text


def test_edit_decision_form_preserves_custom_language_option(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Arabic decision", language="ar", direction="rtl")
    client = TestClient(create_web_app(tmp_path))

    response = client.get(f"/decisions/{record.id}/edit")

    assert response.status_code == 200
    assert '<select id="language" name="language">' in response.text
    assert '<option value="ar" selected>ar</option>' in response.text


def test_ui_creates_persian_rtl_decision(tmp_path: Path) -> None:
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        "/decisions",
        data={
            "title": "تغییر مسیر پرداخت",
            "owner": "CEO",
            "status": "proposed",
            "context": "این تصمیم برای بهبود conversion بررسی می‌شود.",
            "options": "حفظ مسیر فعلی\nکوتاه کردن مسیر پرداخت",
            "decision": "کوتاه کردن مسیر پرداخت",
            "rationale": "کاهش friction",
            "assumptions": "کاربران مسیر کوتاه‌تر را ترجیح می‌دهند.",
            "success_metrics": "conversion_rate",
            "revisit_on": "2026-08-01",
            "language": "fa",
            "direction": "rtl",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = load_decisions(tmp_path, load_config(tmp_path))[0]
    assert record.title == "تغییر مسیر پرداخت"
    assert record.language == "fa"
    assert record.direction == "rtl"
    assert "کاربران مسیر کوتاه‌تر" in record.assumptions[0]["text"]


def test_invalid_status_and_direction_return_form_errors(tmp_path: Path) -> None:
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        "/decisions",
        data={
            "title": "Invalid decision",
            "status": "done",
            "direction": "diagonal",
            "revisit_on": "bad-date",
        },
    )

    assert response.status_code == 422
    assert "Status must be one of" in response.text
    assert "Direction must be auto, ltr, or rtl." in response.text
    assert "Revisit date must use ISO format" in response.text


def test_ui_review_updates_markdown_record(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Review pricing")
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        f"/decisions/{record.id}/review",
        data={
            "outcome": "Gross margin improved.",
            "reviewed_on": "2026-08-15",
            "metric_note": "Retention stayed flat.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert updated.status == "reviewed"
    assert updated.version == 2
    assert updated.outcome == "Gross margin improved."
    assert updated.metadata["metric_notes"] == [{"reviewed_on": "2026-08-15", "note": "Retention stayed flat."}]
    assert "Reviewed on 2026-08-15: Gross margin improved." in updated.body
    assert read_history_events(tmp_path, load_config(tmp_path), record.id)[-1]["action"] == "reviewed"

    detail_response = client.get(f"/decisions/{record.id}")
    assert detail_response.status_code == 200
    assert 'id="reviewed_on" name="reviewed_on" type="date" value="2026-08-15" dir="ltr"' in detail_response.text
    assert "Version history" in detail_response.text
    assert detail_response.text.index("Gross margin improved.") < detail_response.text.index("Scorecard")


def test_ui_review_rejects_invalid_review_date_without_updating_record(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Reject bad review date")
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        f"/decisions/{record.id}/review",
        data={
            "outcome": "Should not save.",
            "reviewed_on": "15-08-2026",
            "metric_note": "Should not save.",
        },
    )

    assert response.status_code == 422
    assert "Review date must use ISO format: YYYY-MM-DD." in response.text
    updated = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert updated.status == "proposed"
    assert updated.outcome == ""
    assert updated.metadata["reviewed_on"] == ""
    assert "Should not save." not in updated.body


def test_dashboard_filters_by_status_and_owner(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    create_decision(tmp_path, config, "Product decision", owner="Product", status="accepted")
    create_decision(tmp_path, config, "CEO decision", owner="CEO", status="proposed")
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/", params={"status": "accepted", "owner": "Product"})

    assert response.status_code == 200
    assert "Product decision" in response.text
    assert "CEO decision" not in response.text


def test_dashboard_parent_cell_links_to_parent_decision(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent decision")
    create_decision(tmp_path, config, "Child decision", parent_id=parent.id)
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert f'<a href="/decisions/{parent.id}">{parent.id}</a>' in response.text


def test_dashboard_paginates_records_and_preserves_filter_query(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    for index in range(12):
        create_decision(
            tmp_path,
            config,
            f"Paged decision {index + 1:02d}",
            owner="Product",
            status="accepted",
            tags=["Paged"],
        )
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/", params={"page": "2", "per_page": "5", "status": "accepted", "tag": "Paged"})

    assert response.status_code == 200
    assert "Showing 6-10 of 12 matching records" in response.text
    assert "Page 2 of 3" in response.text
    assert "Paged decision 06" in response.text
    assert "Paged decision 01" not in response.text
    assert "/?page=1&amp;per_page=5&amp;status=accepted&amp;tag=Paged" in response.text
    assert "/?page=3&amp;per_page=5&amp;status=accepted&amp;tag=Paged" in response.text
    assert "<th>Language</th>" not in response.text


def test_dashboard_filters_by_tag_with_exact_case_insensitive_match(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    pricing = create_decision(tmp_path, config, "Product pricing", owner="Product", status="accepted", tags=["Pricing"])
    create_decision(tmp_path, config, "Product operations", owner="Product", status="accepted", tags=["Operations"])
    create_decision(tmp_path, config, "CEO pricing", owner="CEO", status="accepted", tags=["Pricing"])
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/", params={"status": "accepted", "owner": "Product", "tag": "pricing"})

    assert response.status_code == 200
    assert "Product pricing" in response.text
    assert "Product operations" not in response.text
    assert "CEO pricing" not in response.text
    assert '<option value="Pricing" selected>Pricing</option>' in response.text
    assert 'class="tag-pill" href="/?tag=Pricing"' in response.text

    detail_response = client.get(f"/decisions/{pricing.id}")
    assert detail_response.status_code == 200
    assert 'aria-label="Decision tags"' in detail_response.text
    assert 'class="tag-pill" href="/?tag=Pricing"' in detail_response.text

    empty_response = client.get("/", params={"tag": "price"})
    assert empty_response.status_code == 200
    assert "No decision records match these filters." in empty_response.text
    assert "Product pricing" not in empty_response.text


def test_new_decision_form_supports_parent_prefill(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent decision")
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/decisions/new", params={"parent": parent.id})

    assert response.status_code == 200
    assert "Parent decision" in response.text
    assert f'value="{parent.id}" selected' in response.text


def test_ui_creates_child_with_related_links(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent decision")
    related = create_decision(tmp_path, config, "Related context")
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        "/decisions",
        data={
            "title": "Child decision",
            "status": "proposed",
            "parent_id": parent.id,
            "related_decisions": f"depends_on: {related.id} | Required first",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    child = [record for record in load_decisions(tmp_path, load_config(tmp_path)) if record.title == "Child decision"][0]
    assert child.parent_id == parent.id
    assert child.related_decisions == [{"id": related.id, "type": "depends_on", "note": "Required first"}]

    parent_page = client.get(f"/decisions/{parent.id}")
    assert "Add child decision" in parent_page.text
    assert "Child decision" in parent_page.text

    related_page = client.get(f"/decisions/{related.id}")
    assert "Linked from" in related_page.text
    assert "Child decision" in related_page.text
    assert "Required first" in related_page.text


def test_ui_rejects_invalid_related_decision_type(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    target = create_decision(tmp_path, config, "Target")
    client = TestClient(create_web_app(tmp_path))

    response = client.post(
        "/decisions",
        data={
            "title": "Invalid relation",
            "related_decisions": f"invalid: {target.id}",
        },
    )

    assert response.status_code == 422
    assert "Unsupported relation type: invalid." in response.text


def test_ui_edit_updates_record_without_renaming_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Original title", owner="CEO", revisit_on="2026-09-01")
    original_path = record.path
    client = TestClient(create_web_app(tmp_path))

    edit_response = client.get(f"/decisions/{record.id}/edit")
    assert edit_response.status_code == 200
    assert 'id="revisit_on" name="revisit_on" type="date" value="2026-09-01" dir="ltr"' in edit_response.text
    assert '<select id="language" name="language">' in edit_response.text
    assert '<option value="en" selected>English</option>' in edit_response.text

    response = client.post(
        f"/decisions/{record.id}/edit",
        data={
            "title": "Updated title",
            "owner": "Product",
            "status": "accepted",
            "context": "Updated context",
            "options": "Keep\nChange",
            "decision": "Change",
            "rationale": "Better fit",
            "assumptions": "validated: کاربران تغییر را می‌پذیرند. | Checked",
            "success_metrics": "activation_rate",
            "revisit_on": "2026-09-01",
            "language": "fa",
            "direction": "rtl",
            "tags": "product",
            "body": "# Updated title\n\nManual body stays.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert updated.path == original_path
    assert updated.version == 2
    assert updated.title == "Updated title"
    assert updated.owner == "Product"
    assert updated.status == "accepted"
    assert updated.assumptions == [
        {"text": "کاربران تغییر را می‌پذیرند.", "status": "validated", "note": "Checked"}
    ]
    assert updated.body == "# Updated title\n\nManual body stays."
    assert read_history_events(tmp_path, load_config(tmp_path), record.id)[-1]["changed_fields"] == [
        "assumptions",
        "context",
        "decision",
        "direction",
        "language",
        "options",
        "owner",
        "rationale",
        "status",
        "success_metrics",
        "tags",
        "title",
        "body",
    ]

    snapshot_response = client.get(f"/decisions/{record.id}/history/1")
    assert snapshot_response.status_code == 200
    assert "Snapshot v1" in snapshot_response.text
    assert "Original title" in snapshot_response.text


def test_ui_quick_status_and_assumption_verification(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Verify assumptions", assumptions=["Merchants accept tiers"])
    client = TestClient(create_web_app(tmp_path))

    status_response = client.post(
        f"/decisions/{record.id}/status",
        data={"status": "accepted"},
        follow_redirects=False,
    )
    assumption_response = client.post(
        f"/decisions/{record.id}/assumptions/0",
        data={"status": "validated", "note": "Interviewed 5 merchants"},
        follow_redirects=False,
    )

    updated = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert status_response.status_code == 303
    assert assumption_response.status_code == 303
    assert updated.status == "accepted"
    assert updated.version == 3
    assert updated.assumptions[0]["status"] == "validated"
    assert updated.assumptions[0]["note"] == "Interviewed 5 merchants"
    assert updated.assumptions[0]["reviewed_on"]
    assert [event["action"] for event in read_history_events(tmp_path, load_config(tmp_path), record.id)] == [
        "created",
        "status_updated",
        "assumption_updated",
    ]


def test_ui_adds_and_removes_outgoing_relation(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    source = create_decision(tmp_path, config, "Source")
    target = create_decision(tmp_path, config, "Target")
    client = TestClient(create_web_app(tmp_path))

    add_response = client.post(
        f"/decisions/{source.id}/relations",
        data={"target_id": target.id, "relation_type": "blocks", "note": "Must ship first"},
        follow_redirects=False,
    )
    assert add_response.status_code == 303
    added = load_decision(tmp_path, load_config(tmp_path), source.id)
    assert added.version == 2
    assert added.related_decisions == [
        {"id": target.id, "type": "blocks", "note": "Must ship first"}
    ]

    remove_response = client.post(
        f"/decisions/{source.id}/relations/remove",
        data={"relation_index": "0"},
        follow_redirects=False,
    )

    assert remove_response.status_code == 303
    removed = load_decision(tmp_path, load_config(tmp_path), source.id)
    assert removed.version == 3
    assert removed.related_decisions == []
    assert [event["action"] for event in read_history_events(tmp_path, load_config(tmp_path), source.id)] == [
        "created",
        "relation_added",
        "relation_removed",
    ]


def test_ui_audit_export_and_meeting_parser_actions(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    create_decision(tmp_path, config, "Audit target", assumptions=["Assumption"], revisit_on="2026-01-01")
    client = TestClient(create_web_app(tmp_path))

    audit_response = client.get("/audit")
    export_response = client.post("/export-html")
    parser_preview = client.post(
        "/meeting-parser",
        data={"meeting_text": "- Decision: Launch parser test\nMetric: activation_rate", "action": "preview"},
    )
    parser_create = client.post(
        "/meeting-parser",
        data={
            "meeting_text": "- Decision: Launch parser test\nMetric: activation_rate",
            "action": "create",
            "selected": ["0"],
        },
    )

    assert audit_response.status_code == 200
    assert "Audit target" in audit_response.text
    assert export_response.status_code == 200
    assert (tmp_path / "site" / "index.html").exists()
    assert "Open archive" in export_response.text
    assert parser_preview.status_code == 200
    assert "Launch parser test" in parser_preview.text
    assert parser_create.status_code == 200
    assert any(record.title == "Launch parser test" for record in load_decisions(tmp_path, load_config(tmp_path)))


def test_ui_delete_blocks_referenced_records_and_deletes_unreferenced(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    parent = create_decision(tmp_path, config, "Parent")
    create_decision(tmp_path, config, "Child", parent_id=parent.id)
    free = create_decision(tmp_path, config, "Free")
    client = TestClient(create_web_app(tmp_path))

    blocked = client.post(
        f"/decisions/{parent.id}/delete",
        data={"confirm_id": parent.id},
    )
    deleted = client.post(
        f"/decisions/{free.id}/delete",
        data={"confirm_id": free.id},
        follow_redirects=False,
    )

    assert blocked.status_code == 422
    assert "Delete blocked" in blocked.text
    assert deleted.status_code == 303
    assert not free.path.exists()
    assert read_history_events(tmp_path, load_config(tmp_path), free.id)[-1]["action"] == "deleted"
