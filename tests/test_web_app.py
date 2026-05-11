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
