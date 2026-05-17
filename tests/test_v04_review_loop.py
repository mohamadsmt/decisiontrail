from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from decisiontrail.cli import app
from decisiontrail.config import load_config
from decisiontrail.export import export_html
from decisiontrail.mcp_server import DecisionTrailMCPService
from decisiontrail.storage import create_decision, load_decision
from decisiontrail.web.app import create_web_app


runner = CliRunner()


def test_cli_v04_review_inbox_assumption_plan_and_linked_evidence(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Validate pricing assumption",
        status="accepted",
        assumptions=["Merchants will accept tiers."],
        revisit_on="2026-01-01",
    )

    inbox = runner.invoke(app, ["review-inbox", "--path", str(tmp_path)])
    assert inbox.exit_code == 0
    assert "Decision outcome report" in inbox.output
    assert "Accepted but overdue" in inbox.output

    plan = runner.invoke(app, ["assumptions", "plan", "--path", str(tmp_path)])
    assert plan.exit_code == 0
    assert "Assumption validation plan" in plan.output
    assert "Merchants" in plan.output

    updated = runner.invoke(
        app,
        [
            "assumptions",
            "update",
            record.id,
            "0",
            "pending",
            "--path",
            str(tmp_path),
            "--owner",
            "Product",
            "--due-on",
            "2026-06-01",
            "--signal",
            "Interview five merchants",
            "--note",
            "Validation planned",
        ],
    )
    assert updated.exit_code == 0

    evidence = runner.invoke(
        app,
        [
            "evidence",
            "add",
            record.id,
            "Merchant interviews",
            "--path",
            str(tmp_path),
            "--type",
            "note",
            "--note",
            "Four of five accepted tiers.",
            "--assumption",
            "0",
            "--metric",
            "merchant_retention",
            "--added-on",
            "2026-06-02",
        ],
    )
    assert evidence.exit_code == 0
    assert "EVD-001" in evidence.output

    saved = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert saved.assumptions[0] == {
        "text": "Merchants will accept tiers.",
        "status": "pending",
        "owner": "Product",
        "due_on": "2026-06-01",
        "signal": "Interview five merchants",
        "evidence_refs": ["EVD-001"],
        "note": "Validation planned",
        "reviewed_on": saved.assumptions[0]["reviewed_on"],
    }
    assert saved.metadata["evidence"][0]["id"] == "EVD-001"
    assert saved.metadata["evidence"][0]["links"] == [
        {"type": "assumption", "target": "0"},
        {"type": "metric", "target": "merchant_retention"},
    ]

    listed = runner.invoke(app, ["evidence", "list", record.id, "--path", str(tmp_path)])
    assert listed.exit_code == 0
    assert "EVD-001" in listed.output


def test_web_v04_review_inbox_forms_update_assumptions_and_link_evidence(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Review loop decision",
        assumptions=["Users will understand the change."],
        revisit_on="2026-01-01",
    )
    client = TestClient(create_web_app(tmp_path))

    review = client.get("/review")
    assert review.status_code == 200
    assert "Decision outcome report" in review.text
    assert "Save assumption" in review.text

    assumption = client.post(
        f"/decisions/{record.id}/assumptions/0",
        data={
            "status": "pending",
            "owner": "Research",
            "due_on": "2026-06-15",
            "signal": "Three interviews",
            "note": "Waiting on cohort data",
            "evidence_refs": "",
        },
        follow_redirects=False,
    )
    assert assumption.status_code == 303

    evidence = client.post(
        f"/decisions/{record.id}/evidence",
        data={
            "title": "Interview notes",
            "evidence_type": "note",
            "note": "Participants understood the change.",
            "added_on": "2026-06-16",
            "assumption_index": "0",
            "metric_name": "activation_rate",
        },
        follow_redirects=False,
    )
    assert evidence.status_code == 303

    saved = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert saved.assumptions[0]["owner"] == "Research"
    assert saved.assumptions[0]["due_on"] == "2026-06-15"
    assert saved.assumptions[0]["signal"] == "Three interviews"
    assert saved.assumptions[0]["evidence_refs"] == ["EVD-001"]
    assert saved.metadata["evidence"][0]["links"][1] == {"type": "metric", "target": "activation_rate"}

    invalid = client.post(
        f"/decisions/{record.id}/assumptions/0",
        data={"status": "pending", "due_on": "15-06-2026"},
    )
    assert invalid.status_code == 422
    assert "due_on must use ISO format" in invalid.text


def test_export_v04_writes_outcome_report_page(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Supersede candidate",
        status="accepted",
        assumptions=[{"text": "Assumption failed.", "status": "invalidated"}],
        revisit_on="2026-01-01",
    )

    export_html([record], tmp_path / "site", config)

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    report_html = (tmp_path / "site" / "outcome-report.html").read_text(encoding="utf-8")
    assert "outcome-report.html" in index_html
    assert "Outcome report" in report_html
    assert "Supersede candidate" in report_html
    assert record.id in report_html


def test_mcp_v04_review_inbox_draft_context_and_linked_evidence(tmp_path: Path) -> None:
    service = DecisionTrailMCPService(tmp_path)
    created = service.record_decision(
        title="AI pricing review",
        status="accepted",
        assumptions=[{"text": "Users trust the recommendation.", "status": "unvalidated"}],
        revisit_on="2026-01-01",
        created_on="2026-05-12",
    )
    record_id = created["record"]["id"]

    context = service.draft_context("pricing recommendation", limit=10)
    assert context["limit"] == 5
    assert context["context_records"][0]["id"] == record_id
    assert "draft" in context["instruction"]

    inbox = service.review_inbox()
    assert inbox["due"][0]["id"] == record_id
    assert inbox["accepted_overdue"][0]["id"] == record_id

    updated = service.update_assumption(
        record_id,
        0,
        "pending",
        owner="Product",
        due_on="2026-06-01",
        signal="Collect five support examples",
        evidence_refs=["EVD-900"],
    )
    assert updated["record"]["metadata"]["assumptions"][0]["owner"] == "Product"

    evidence = service.add_evidence(
        record_id,
        title="Support examples",
        evidence_type="note",
        note="Examples collected.",
        assumption_index=0,
        metric_name="support_ticket_rate",
        added_on="2026-06-02",
    )
    assert evidence["item"]["id"] == "EVD-001"
    assert evidence["item"]["links"] == [
        {"type": "assumption", "target": "0"},
        {"type": "metric", "target": "support_ticket_rate"},
    ]
    assert "EVD-001" in evidence["record"]["metadata"]["assumptions"][0]["evidence_refs"]
