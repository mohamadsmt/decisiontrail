from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from decisiontrail.config import load_config
from decisiontrail.storage import create_decision, load_decision, load_decisions
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
    assert 'dir="auto"' in response.text


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
    assert updated.outcome == "Gross margin improved."
    assert updated.metadata["metric_notes"] == [{"reviewed_on": "2026-08-15", "note": "Retention stayed flat."}]
    assert "Reviewed on 2026-08-15: Gross margin improved." in updated.body


def test_dashboard_filters_by_status_and_owner(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    create_decision(tmp_path, config, "Product decision", owner="Product", status="accepted")
    create_decision(tmp_path, config, "CEO decision", owner="CEO", status="proposed")
    client = TestClient(create_web_app(tmp_path))

    response = client.get("/", params={"status": "accepted", "owner": "Product"})

    assert response.status_code == 200
    assert "Product decision" in response.text
    assert "CEO decision" not in response.text


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
    record = create_decision(tmp_path, config, "Original title", owner="CEO")
    original_path = record.path
    client = TestClient(create_web_app(tmp_path))

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
    assert updated.title == "Updated title"
    assert updated.owner == "Product"
    assert updated.status == "accepted"
    assert updated.assumptions == [
        {"text": "کاربران تغییر را می‌پذیرند.", "status": "validated", "note": "Checked"}
    ]
    assert updated.body == "# Updated title\n\nManual body stays."


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
    assert updated.assumptions[0]["status"] == "validated"
    assert updated.assumptions[0]["note"] == "Interviewed 5 merchants"
    assert updated.assumptions[0]["reviewed_on"]


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
    assert load_decision(tmp_path, load_config(tmp_path), source.id).related_decisions == [
        {"id": target.id, "type": "blocks", "note": "Must ship first"}
    ]

    remove_response = client.post(
        f"/decisions/{source.id}/relations/remove",
        data={"relation_index": "0"},
        follow_redirects=False,
    )

    assert remove_response.status_code == 303
    assert load_decision(tmp_path, load_config(tmp_path), source.id).related_decisions == []


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
