from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from decisiontrail.config import load_config
import decisiontrail.mcp_server as mcp_server
from decisiontrail.mcp_server import DecisionTrailMCPService, main, parse_args, resolve_root
from decisiontrail.storage import create_decision, load_decision


def test_mcp_service_records_updates_reviews_and_exports_decision(tmp_path: Path) -> None:
    service = DecisionTrailMCPService(tmp_path)

    created = service.record_decision(
        title="تغییر مسیر پرداخت",
        owner="CEO",
        context="این تصمیم برای بهبود conversion بررسی می‌شود.",
        options=["حفظ مسیر فعلی", "کوتاه کردن مسیر پرداخت"],
        decision="کوتاه کردن مسیر پرداخت",
        rationale=["کاهش friction"],
        assumptions=[{"text": "کاربران مسیر کوتاه‌تر را ترجیح می‌دهند.", "status": "unvalidated"}],
        success_metrics=["conversion_rate"],
        revisit_on="2026-08-01",
        tags=["checkout"],
        created_on="2026-05-12",
    )

    record_id = created["record"]["id"]
    original_path = created["path"]
    assert created["action"] == "created"
    assert created["record"]["language"] == "fa"
    assert created["record"]["direction"] == "rtl"

    updated = service.update_decision(record_id, owner="Product", body="# Custom body\n")
    assert updated["path"] == original_path
    assert updated["record"]["owner"] == "Product"
    assert updated["record"]["body"] == "# Custom body\n"

    status = service.update_status(record_id, "accepted")
    assert status["record"]["status"] == "accepted"

    assumption = service.update_assumption(
        record_id,
        0,
        "validated",
        note="Confirmed by cohort data",
        reviewed_on="2026-08-15",
    )
    assert assumption["record"]["metadata"]["assumptions"][0]["status"] == "validated"

    reviewed = service.review_decision(
        record_id,
        outcome="Conversion improved.",
        reviewed_on="2026-09-01",
        metric_note="No support increase.",
    )
    assert reviewed["record"]["status"] == "reviewed"
    assert reviewed["record"]["metadata"]["metric_notes"] == [
        {"reviewed_on": "2026-09-01", "note": "No support increase."}
    ]

    audit = service.audit_decisions()
    assert audit["issues"] == []

    exported = service.export_html()
    assert exported["page_count"] == 2
    assert (tmp_path / "site" / "index.html").exists()


def test_mcp_service_relationships_parse_meeting_and_guarded_delete(tmp_path: Path) -> None:
    service = DecisionTrailMCPService(tmp_path)
    parent = service.record_decision(title="Parent", created_on="2026-05-12")["record"]
    target = service.record_decision(title="Target", created_on="2026-05-12")["record"]
    child = service.record_decision(title="Child", parent_id=parent["id"], created_on="2026-05-12")["record"]

    related = service.add_relation(child["id"], target["id"], relation_type="depends_on", note="Required first")
    assert related["record"]["outgoing_relations"][0]["target_id"] == target["id"]

    removed = service.remove_relation(child["id"], 0)
    assert removed["record"]["outgoing_relations"] == []

    blocked = service.delete_decision(parent["id"], confirm_id=parent["id"])
    assert blocked["deleted"] is False
    assert "child decisions" in " ".join(blocked["errors"])

    free = service.record_decision(title="Free", created_on="2026-05-12")["record"]
    deleted = service.delete_decision(free["id"], confirm_id=free["id"])
    assert deleted["deleted"] is True
    assert not Path(deleted["path"]).exists()

    parsed = service.parse_meeting("- Decision: Launch parser\nMetric: activation_rate", write=False)
    assert parsed["drafts"][0]["title"] == "Launch parser"

    written = service.parse_meeting(
        "- Decision: Write parser draft\nMetric: retention",
        write=True,
        selected_indexes=[0],
        owner="Product",
    )
    assert written["created"][0]["owner"] == "Product"

    with pytest.raises(ValueError, match="Relation type must be one of"):
        service.add_relation(child["id"], target["id"], relation_type="bad")


def test_mcp_cli_help_and_argument_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "decisiontrail-mcp" in capsys.readouterr().out

    args = parse_args(
        [
            "--path",
            str(tmp_path),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
            "--path-prefix",
            "/mcp",
        ]
    )
    assert args.path == str(tmp_path)
    assert args.transport == "streamable-http"
    assert args.port == 9000

    monkeypatch.setenv("DECISIONTRAIL_ROOT", str(tmp_path))
    assert resolve_root() == tmp_path.resolve()


def test_mcp_http_main_wires_fastmcp_constructor_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeServer:
        def run(self, **kwargs):
            captured["run"] = kwargs

    def fake_create(service, **kwargs):
        captured["root"] = service.root
        captured["create"] = kwargs
        return FakeServer()

    monkeypatch.setattr(mcp_server, "create_mcp_server", fake_create)

    main(
        [
            "--path",
            str(tmp_path),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "9999",
            "--path-prefix",
            "/custom-mcp",
        ]
    )

    assert captured["root"] == tmp_path.resolve()
    assert captured["create"] == {
        "host": "127.0.0.1",
        "port": 9999,
        "path_prefix": "/custom-mcp",
        "json_response": True,
        "stateless_http": True,
    }
    assert captured["run"] == {"transport": "streamable-http"}


def test_mcp_stdio_smoke_lists_tools_and_records_decision(tmp_path: Path) -> None:
    async def run_smoke() -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "decisiontrail.mcp_server", "--path", str(tmp_path)],
            env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                resources = await session.list_resources()
                prompts = await session.list_prompts()

                tool_names = {tool.name for tool in tools.tools}
                resource_uris = {str(resource.uri) for resource in resources.resources}
                prompt_names = {prompt.name for prompt in prompts.prompts}
                assert {"record_decision", "get_decision", "audit_decisions"}.issubset(tool_names)
                assert "decisiontrail://schema" in resource_uris
                assert "capture_decision_from_rough" in prompt_names

                created = await session.call_tool(
                    "record_decision",
                    arguments={
                        "title": "Agent decision",
                        "owner": "Product",
                        "options": ["Keep", "Change"],
                        "decision": "Change",
                        "rationale": ["Better fit"],
                        "success_metrics": ["activation_rate"],
                        "created_on": "2026-05-12",
                    },
                )
                created_data = _tool_data(created)
                record_id = created_data["record"]["id"]

                fetched = await session.call_tool("get_decision", arguments={"identifier": record_id})
                assert _tool_data(fetched)["title"] == "Agent decision"

                audit = await session.call_tool("audit_decisions", arguments={})
                assert "issues" in _tool_data(audit)

    asyncio.run(run_smoke())


def test_mcp_service_works_with_existing_storage_records(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Existing decision", owner="CEO", tags=["Strategy"])
    create_decision(tmp_path, config, "Other decision", owner="CEO", tags=["Operations"])

    service = DecisionTrailMCPService(tmp_path)

    listed = service.list_decisions(owner="CEO", tag="strategy")
    assert listed["records"][0]["id"] == record.id
    assert listed["records"][0]["tags"] == ["Strategy"]
    assert service.list_decisions(tag="strat")["records"] == []
    assert service.search_decisions("existing", tag="strategy")["records"][0]["id"] == record.id
    assert service.search_decisions("existing", tag="operations")["records"] == []
    assert service.get_decision(record.id)["title"] == "Existing decision"


def _tool_data(result) -> dict:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured:
        return structured
    text = result.content[0].text
    return json.loads(text)
