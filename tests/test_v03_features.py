from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from decisiontrail.cli import app
from decisiontrail.config import load_config
from decisiontrail.mcp_server import DecisionTrailMCPService
from decisiontrail.storage import create_decision, load_decision, read_history_events
from decisiontrail.web.app import create_web_app


runner = CliRunner()


def test_cli_v03_evidence_metrics_drafts_views_graph_diff_and_restore(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    created = runner.invoke(
        app,
        [
            "new",
            "Launch pricing test",
            "--path",
            str(tmp_path),
            "--type",
            "pricing",
            "--tag",
            "Pricing",
        ],
    )
    assert created.exit_code == 0

    evidence = runner.invoke(
        app,
        [
            "evidence",
            "add",
            "DEC-2026-001",
            "Margin sheet",
            "--path",
            str(tmp_path),
            "--type",
            "url",
            "--ref",
            "https://example.com/margin",
            "--added-on",
            "2026-08-01",
        ],
    )
    assert evidence.exit_code == 0
    metrics = runner.invoke(
        app,
        [
            "metric",
            "add",
            "DEC-2026-001",
            "gross_margin",
            "--path",
            str(tmp_path),
            "--value",
            "42%",
            "--measured-on",
            "2026-08-02",
        ],
    )
    assert metrics.exit_code == 0

    record = load_decision(tmp_path, load_config(tmp_path), "DEC-2026-001")
    assert record.decision_type == "pricing"
    assert record.metadata["evidence"][0]["title"] == "Margin sheet"
    assert record.metadata["metric_updates"][0]["value"] == "42%"

    search = runner.invoke(app, ["search", "pricing", "--path", str(tmp_path)])
    assert search.exit_code == 0
    assert "Launch pricing test" in search.output
    graph = runner.invoke(app, ["graph", "--path", str(tmp_path), "--format", "json"])
    assert graph.exit_code == 0
    assert "Launch pricing test" in graph.output

    note = tmp_path / "meeting.md"
    note.write_text("- Decision: Draft parser decision\nMetric: activation_rate\n", encoding="utf-8")
    parsed = runner.invoke(app, ["parse-meeting", str(note), "--path", str(tmp_path)])
    assert parsed.exit_code == 0
    assert "Saved draft" in parsed.output
    drafts = runner.invoke(app, ["drafts", "list", "--path", str(tmp_path)])
    assert drafts.exit_code == 0
    assert "Draft parser decision" in drafts.output
    promoted = runner.invoke(app, ["drafts", "promote", "DRAFT-2026-001", "--path", str(tmp_path)])
    assert promoted.exit_code == 0
    assert "DEC-2026-002" in promoted.output

    saved = runner.invoke(app, ["views", "save", "Pricing local", "--path", str(tmp_path), "--q", "pricing"])
    assert saved.exit_code == 0
    views = runner.invoke(app, ["views", "list", "--path", str(tmp_path)])
    assert views.exit_code == 0
    assert "Pricing local" in views.output

    diff = runner.invoke(app, ["diff", "DEC-2026-001", "--path", str(tmp_path), "--from", "1"])
    assert diff.exit_code == 0
    assert "Margin sheet" in diff.output
    restored = runner.invoke(
        app,
        ["restore", "DEC-2026-001", "--path", str(tmp_path), "--version", "1", "--confirm-id", "DEC-2026-001"],
    )
    assert restored.exit_code == 0
    assert "as v4" in restored.output


def test_web_v03_review_graph_drafts_evidence_metrics_and_restore(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Evidence decision", success_metrics=["retention"], revisit_on="2026-01-01")
    client = TestClient(create_web_app(tmp_path))

    assert client.get("/review").status_code == 200
    graph = client.get("/graph")
    assert graph.status_code == 200
    assert "decision-graph" in graph.text

    drafts = client.post("/drafts/from-meeting", data={"meeting_text": "- Decision: Web draft\nMetric: activation_rate"})
    assert drafts.status_code == 200
    assert "Web draft" in drafts.text
    promoted = client.post("/drafts/DRAFT-2026-001/promote", data={"owner": "Product", "status": "proposed"}, follow_redirects=False)
    assert promoted.status_code == 303

    evidence = client.post(
        f"/decisions/{record.id}/evidence",
        data={"title": "Experiment note", "evidence_type": "note", "note": "Cohort looked healthy.", "added_on": "2026-08-01"},
        follow_redirects=False,
    )
    assert evidence.status_code == 303
    metric = client.post(
        f"/decisions/{record.id}/metrics",
        data={"name": "retention", "value": "flat", "measured_on": "2026-08-02"},
        follow_redirects=False,
    )
    assert metric.status_code == 303
    updated = load_decision(tmp_path, load_config(tmp_path), record.id)
    assert updated.metadata["evidence"][0]["title"] == "Experiment note"
    assert updated.metadata["metric_updates"][0]["name"] == "retention"

    snapshot = client.get(f"/decisions/{record.id}/history/1")
    assert snapshot.status_code == 200
    assert "Diff to current" in snapshot.text
    restored = client.post(
        f"/decisions/{record.id}/history/1/restore",
        data={"confirm_id": record.id},
        follow_redirects=False,
    )
    assert restored.status_code == 303


def test_mcp_v03_tools_cover_annotations_drafts_views_graph_and_restore(tmp_path: Path) -> None:
    service = DecisionTrailMCPService(tmp_path)
    created = service.record_decision(title="AI risk decision", tags=["AI", "risk"], created_on="2026-05-12")
    record_id = created["record"]["id"]

    evidence = service.add_evidence(record_id, title="Risk note", evidence_type="note", note="Needs guardrails.", added_on="2026-08-01")
    assert evidence["item"]["title"] == "Risk note"
    metric = service.add_metric_update(record_id, name="latency", value="800ms", measured_on="2026-08-02")
    assert metric["item"]["value"] == "800ms"
    assert service.search_decisions("", view="AI")["records"][0]["id"] == record_id

    diff = service.diff_decision(record_id, from_version=1)
    assert "Risk note" in diff["diff"]
    restored = service.restore_decision(record_id, version=1, confirm_id=record_id)
    assert restored["version"] == 4

    parsed = service.parse_meeting("- Decision: MCP draft\nMetric: activation_rate", write=False)
    assert parsed["stored_drafts"][0]["title"] == "MCP draft"
    drafts = service.list_drafts()
    assert drafts["drafts"][0]["title"] == "MCP draft"
    promoted = service.promote_draft(drafts["drafts"][0]["id"], owner="Product")
    assert promoted["record"]["owner"] == "Product"

    view = service.save_view(name="Risk local", q="risk")
    assert view["view"]["name"] == "Risk local"
    assert service.list_views()["views"]
    assert "AI risk decision" in service.graph(format="mermaid")["graph"]
    assert read_history_events(tmp_path, load_config(tmp_path), record_id)[-1]["action"] == "restored"
