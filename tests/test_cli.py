from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from decisiontrail.cli import app


runner = CliRunner()


def test_cli_init_new_list_and_score(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "new",
            "Launch pricing",
            "--path",
            str(tmp_path),
            "--owner",
            "Product",
            "--tag",
            "Pricing",
            "--tag",
            "Growth",
            "--revisit-on",
            "2026-07-15",
        ],
    )
    assert result.exit_code == 0
    assert "DEC-" in result.output

    result = runner.invoke(app, ["list", "--path", str(tmp_path), "--owner", "Product"])
    assert result.exit_code == 0
    assert "DEC-2026-001" in result.output
    assert "Pricing" in result.output
    assert "Growth" in result.output

    result = runner.invoke(app, ["list", "--path", str(tmp_path), "--tag", "pricing"])
    assert result.exit_code == 0
    assert "DEC-2026-001" in result.output

    result = runner.invoke(app, ["list", "--path", str(tmp_path), "--tag", "price"])
    assert result.exit_code == 0
    assert "DEC-2026-001" not in result.output

    result = runner.invoke(app, ["score", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "Decision scorecard" in result.output


def test_cli_review_updates_record(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    runner.invoke(app, ["new", "Reviewable decision", "--path", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "review",
            "DEC-2026-001",
            "--path",
            str(tmp_path),
            "--outcome",
            "The decision worked.",
            "--reviewed-on",
            "2026-08-01",
        ],
    )

    assert result.exit_code == 0
    content = next((tmp_path / "decisions").glob("*.md")).read_text(encoding="utf-8")
    assert "status: reviewed" in content
    assert "The decision worked." in content


def test_cli_run_weekly_review_and_check_warn_by_default(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    runner.invoke(
        app,
        [
            "new",
            "Overdue decision",
            "--path",
            str(tmp_path),
            "--revisit-on",
            "2026-01-01",
        ],
    )

    result = runner.invoke(app, ["run", "weekly-review", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "Decisions due for review" in result.output

    result = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "warning-only" in result.output


def test_cli_export_and_parse_meeting(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    runner.invoke(app, ["new", "Export decision", "--path", str(tmp_path)])

    result = runner.invoke(app, ["export", "--path", str(tmp_path), "--format", "html"])
    assert result.exit_code == 0
    assert (tmp_path / "site" / "index.html").exists()

    note = tmp_path / "meeting.md"
    note.write_text("- Decision: Test parser\nMetric: activation_rate\n", encoding="utf-8")
    result = runner.invoke(app, ["parse-meeting", str(note), "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "Test parser" in result.output


def test_cli_relationship_commands(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    parent = runner.invoke(app, ["new", "Parent decision", "--path", str(tmp_path)])
    assert parent.exit_code == 0

    child = runner.invoke(
        app,
        [
            "new",
            "Child decision",
            "--path",
            str(tmp_path),
            "--parent",
            "DEC-2026-001",
            "--related",
            "depends_on:DEC-2026-001",
        ],
    )
    assert child.exit_code == 0

    related = runner.invoke(
        app,
        [
            "relate",
            "DEC-2026-002",
            "DEC-2026-001",
            "--path",
            str(tmp_path),
            "--type",
            "informs",
            "--note",
            "Pricing context",
        ],
    )
    assert related.exit_code == 0
    assert "informs" in related.output

    links = runner.invoke(app, ["links", "DEC-2026-001", "--path", str(tmp_path)])
    assert links.exit_code == 0
    assert "Children" in links.output
    assert "Child decision" in links.output
    assert "Linked from" in links.output
    assert "Pricing context" in links.output

    tree = runner.invoke(app, ["tree", "--path", str(tmp_path)])
    assert tree.exit_code == 0
    assert "DecisionTrail" in tree.output
    assert "Parent decision" in tree.output
    assert "Child decision" in tree.output


def test_cli_new_rejects_invalid_relation_type(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path), "--no-sample"])
    runner.invoke(app, ["new", "Parent decision", "--path", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "new",
            "Bad relation",
            "--path",
            str(tmp_path),
            "--related",
            "bad_type:DEC-2026-001",
        ],
    )

    assert result.exit_code != 0
    assert "Relation type must be one of" in result.output
