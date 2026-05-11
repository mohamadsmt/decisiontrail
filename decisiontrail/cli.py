from __future__ import annotations

import webbrowser
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from decisiontrail.config import dump_default_config, load_config
from decisiontrail.export import export_html
from decisiontrail.models import VALID_DIRECTIONS, VALID_RELATION_TYPES, VALID_STATUSES
from decisiontrail.parser import parse_meeting_notes
from decisiontrail.relationships import (
    append_relation,
    backlinks,
    children_of,
    outgoing_relations,
    parse_relation_args,
    parse_relation_line,
    relation_to_metadata,
    relation_type_label,
)
from decisiontrail.review import (
    assumption_items,
    missing_metrics,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import (
    create_decision,
    ensure_template,
    load_decision,
    load_decisions,
    write_decision,
)


app = typer.Typer(help="Local-first decision records for product, business, and strategy work.")
run_app = typer.Typer(help="Run built-in local actions.")
app.add_typer(run_app, name="run")
console = Console()


def _root(path: Path) -> Path:
    return path.expanduser().resolve()


def _load(path: Path):
    root = _root(path)
    return root, load_config(root)


@app.command()
def init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    sample: bool = typer.Option(True, "--sample/--no-sample", help="Create sample decision records."),
) -> None:
    """Initialize a local DecisionTrail project."""
    root = _root(path)
    root.mkdir(parents=True, exist_ok=True)
    dump_default_config(root)
    config = load_config(root)
    (root / config.decisions_dir).mkdir(parents=True, exist_ok=True)
    ensure_template(root, config)

    created = []
    if sample and not load_decisions(root, config):
        created.append(
            create_decision(
                root,
                config,
                "Launch tiered pricing for high-volume merchants",
                status="accepted",
                owner="Product",
                created_on=date(2026, 5, 11),
                context="Current pricing creates margin pressure for high-volume merchants.",
                options=["Keep current pricing", "Increase flat fee", "Launch tiered pricing"],
                decision="Launch tiered pricing",
                rationale=[
                    "Better margin control",
                    "Lower churn risk than a flat fee increase",
                    "Easier to test with a segment",
                ],
                assumptions=[
                    {
                        "text": "High-volume merchants care more about reliability than small fee changes.",
                        "status": "unvalidated",
                    }
                ],
                success_metrics=["gross_margin", "merchant_retention", "support_ticket_rate"],
                revisit_on="2026-07-15",
                language="en",
                direction="auto",
                tags=["pricing", "growth"],
            )
        )
        created.append(
            create_decision(
                root,
                config,
                "تغییر مدل قیمت‌گذاری برای فروشنده‌های بزرگ",
                status="proposed",
                owner="CEO",
                created_on=date(2026, 5, 11),
                context="این تصمیم برای کاهش فشار روی gross margin و حفظ retention بررسی می‌شود.",
                options=["حفظ قیمت فعلی", "افزایش کارمزد ثابت", "ساخت پلن tiered"],
                decision="ساخت پلن tiered برای segment فروشنده‌های بزرگ",
                rationale=["ریسک churn کمتر از افزایش مستقیم قیمت است.", "امکان تست محدود روی segment مشخص وجود دارد."],
                assumptions=[
                    {
                        "text": "فروشنده‌های بزرگ نسبت به reliability حساس‌تر از تغییر کوچک fee هستند.",
                        "status": "unvalidated",
                    }
                ],
                success_metrics=["gross_margin", "merchant_retention"],
                revisit_on="2026-07-15",
                language="fa",
                direction="rtl",
                tags=["pricing", "persian"],
            )
        )

    console.print(f"Initialized DecisionTrail at [bold]{root}[/bold]")
    if created:
        console.print(f"Created {len(created)} sample decisions.")


@app.command()
def new(
    title: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    owner: str = typer.Option("", "--owner", help="Decision owner."),
    status: str = typer.Option("proposed", "--status", help="Decision status."),
    language: str = typer.Option("en", "--language", help="Content language code."),
    direction: str = typer.Option("auto", "--direction", help="Text direction: auto, ltr, or rtl."),
    revisit_on: str = typer.Option("", "--revisit-on", help="ISO revisit date."),
    parent: str = typer.Option("", "--parent", help="Parent decision ID."),
    related: Optional[list[str]] = typer.Option(None, "--related", help="Typed relation, e.g. depends_on:DEC-2026-002."),
) -> None:
    """Create a new decision record."""
    if status not in VALID_STATUSES:
        raise typer.BadParameter(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    if direction not in VALID_DIRECTIONS:
        raise typer.BadParameter("Direction must be auto, ltr, or rtl.")

    root, config = _load(path)
    ensure_template(root, config)
    records = load_decisions(root, config)
    known_ids = {record.id for record in records}
    related_decisions = parse_relation_args(related or [])
    if parent and parent not in known_ids:
        raise typer.BadParameter(f"Unknown parent decision: {parent}")
    for relation in related_decisions:
        if relation.relation_type not in VALID_RELATION_TYPES:
            raise typer.BadParameter(f"Relation type must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}.")
        if relation.target_id not in known_ids:
            raise typer.BadParameter(f"Unknown related decision: {relation.target_id}")
    record = create_decision(
        root,
        config,
        title,
        owner=owner,
        status=status,
        language=language,
        direction=direction,
        revisit_on=revisit_on,
        parent_id=parent,
        related_decisions=[relation_to_metadata(relation) for relation in related_decisions],
    )
    console.print(f"Created [bold]{record.id}[/bold]: {record.path}")


@app.command(name="list")
def list_decisions(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter by owner."),
    due_before: Optional[str] = typer.Option(None, "--due-before", help="Filter records due on or before an ISO date."),
) -> None:
    """List decision records."""
    root, config = _load(path)
    records = load_decisions(root, config)
    if status:
        records = [record for record in records if record.status == status]
    if owner:
        records = [record for record in records if record.owner.lower() == owner.lower()]
    if due_before:
        target = date.fromisoformat(due_before)
        records = [record for record in records if record.revisit_on and record.revisit_on <= target]

    table = Table(title="Decision records")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Owner")
    table.add_column("Parent")
    table.add_column("Revisit")
    table.add_column("Title")
    for record in records:
        table.add_row(record.id, record.status, record.owner or "-", record.parent_id or "-", str(record.revisit_on or "-"), record.title)
    console.print(table)


@app.command()
def due(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Show decisions due for review."""
    root, config = _load(path)
    records = weekly_review(load_decisions(root, config))["due"]
    if not records:
        console.print("No decisions are due for review.")
        return
    _print_records("Decisions due for review", records)


@app.command()
def assumptions(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """List tracked assumptions."""
    root, config = _load(path)
    items = assumption_items(load_decisions(root, config))
    table = Table(title="Assumptions")
    table.add_column("Decision")
    table.add_column("Status")
    table.add_column("Assumption")
    for item in items:
        table.add_row(item.decision_id, item.status, item.text)
    console.print(table)


@app.command()
def score(
    identifier: Optional[str] = typer.Argument(None, help="Decision ID. Omit to score all records."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """Score decision record quality."""
    root, config = _load(path)
    records = [load_decision(root, config, identifier)] if identifier else load_decisions(root, config)
    table = Table(title="Decision scorecard")
    table.add_column("ID")
    table.add_column("Score", justify="right")
    table.add_column("Missing")
    table.add_column("Warnings")
    for record in records:
        result = score_decision(record)
        table.add_row(record.id, str(result.score), ", ".join(result.missing) or "-", ", ".join(result.warnings) or "-")
    console.print(table)


@app.command()
def review(
    identifier: str,
    outcome: str = typer.Option(..., "--outcome", help="Measured outcome or review note."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    reviewed_on: str = typer.Option("", "--reviewed-on", help="ISO review date. Defaults to today."),
    metric_note: str = typer.Option("", "--metric-note", help="Optional metric note."),
) -> None:
    """Record an outcome review for a decision."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    review_date = reviewed_on or date.today().isoformat()
    record.metadata["outcome"] = outcome
    record.metadata["reviewed_on"] = review_date
    record.metadata["status"] = "reviewed"
    if metric_note:
        notes = record.metadata.get("metric_notes") or []
        if not isinstance(notes, list):
            notes = [notes]
        notes.append({"reviewed_on": review_date, "note": metric_note})
        record.metadata["metric_notes"] = notes

    if "## Outcome Review" not in record.body:
        record.body = record.body.rstrip() + "\n\n## Outcome Review\n\n"
    record.body = record.body.rstrip() + f"\n\nReviewed on {review_date}: {outcome}\n"
    write_decision(record)
    console.print(f"Reviewed [bold]{record.id}[/bold].")


@app.command()
def relate(
    source_id: str,
    target_id: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    relation_type: str = typer.Option("related_to", "--type", help="Relation type."),
    note: str = typer.Option("", "--note", help="Optional relation note."),
) -> None:
    """Add a typed relation from one decision to another."""
    root, config = _load(path)
    records = load_decisions(root, config)
    source = load_decision(root, config, source_id)
    target = load_decision(root, config, target_id)
    relation = parse_relation_line(f"{relation_type}:{target.id}" + (f" | {note}" if note else ""), source_id=source.id)
    if relation is None:
        raise typer.BadParameter("Relation could not be parsed.")
    temp_records = [record for record in records if record.id != source.id] + [source]
    if source.id == target.id:
        raise typer.BadParameter("A decision cannot relate to itself.")
    if relation_type not in VALID_RELATION_TYPES:
        raise typer.BadParameter(f"Relation type must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}.")
    append_relation(source, relation)
    issues = validate_record(source, records=temp_records)
    relation_issues = [issue for issue in issues if "related_decisions" in issue or "relation type" in issue]
    if relation_issues:
        raise typer.BadParameter("; ".join(relation_issues))
    write_decision(source)
    console.print(f"Related [bold]{source.id}[/bold] {relation_type_label(relation.relation_type)} [bold]{target.id}[/bold].")


@app.command()
def links(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """Show parent, children, outgoing links, and backlinks for a decision."""
    root, config = _load(path)
    records = load_decisions(root, config)
    record = load_decision(root, config, identifier)
    records_by_id = {item.id: item for item in records}

    console.print(f"[bold]{record.id}[/bold] {record.title}")
    parent = records_by_id.get(record.parent_id) if record.parent_id else None
    console.print(f"Parent: {parent.id + ' ' + parent.title if parent else '-'}")
    _print_link_rows("Children", [(child.id, "child", child.title, "") for child in children_of(records, record.id)])
    _print_link_rows(
        "Outgoing links",
        [
            (
                relation.target_id,
                relation.relation_type,
                records_by_id.get(relation.target_id).title if records_by_id.get(relation.target_id) else "",
                relation.note,
            )
            for relation in outgoing_relations(record)
        ],
    )
    _print_link_rows(
        "Linked from",
        [
            (
                relation.source_id,
                relation.relation_type,
                records_by_id.get(relation.source_id).title if records_by_id.get(relation.source_id) else "",
                relation.note,
            )
            for relation in backlinks(records, record.id)
        ],
    )


@app.command()
def tree(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Show the decision hierarchy."""
    from rich.tree import Tree as RichTree

    root, config = _load(path)
    records = load_decisions(root, config)
    by_parent: dict[str, list] = {}
    ids = {record.id for record in records}
    for record in records:
        by_parent.setdefault(record.parent_id, []).append(record)

    rich_tree = RichTree("DecisionTrail")
    rendered: set[str] = set()

    def add_nodes(parent_node, parent_id: str, seen: set[str]) -> None:
        for record in by_parent.get(parent_id, []):
            label = f"{record.id} {record.title}"
            node = parent_node.add(label)
            rendered.add(record.id)
            if record.id in seen:
                node.add("cycle detected")
                continue
            add_nodes(node, record.id, seen | {record.id})

    add_nodes(rich_tree, "", set())
    for orphan_parent_id in sorted(parent_id for parent_id in by_parent if parent_id and parent_id not in ids):
        orphan_node = rich_tree.add(f"Unresolved parent {orphan_parent_id}")
        add_nodes(orphan_node, orphan_parent_id, set())
    remaining = [record for record in records if record.id not in rendered]
    if remaining:
        detached_node = rich_tree.add("Cycles or detached records")
        for record in remaining:
            if record.id in rendered:
                continue
            node = detached_node.add(f"{record.id} {record.title}")
            rendered.add(record.id)
            add_nodes(node, record.id, {record.id})
    console.print(rich_tree)


@app.command()
def parse_meeting(
    meeting_file: Path,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    write: bool = typer.Option(False, "--write", help="Write extracted drafts as decision records."),
) -> None:
    """Extract draft decisions from a Markdown meeting note."""
    root, config = _load(path)
    drafts = parse_meeting_notes(meeting_file)
    if not drafts:
        console.print("No decision candidates found.")
        return

    table = Table(title="Draft decisions")
    table.add_column("Title")
    table.add_column("Options")
    table.add_column("Assumptions")
    table.add_column("Metrics")
    for draft in drafts:
        table.add_row(
            draft.title,
            str(len(draft.options)),
            str(len(draft.assumptions)),
            str(len(draft.success_metrics)),
        )
    console.print(table)

    if write:
        for draft in drafts:
            record = create_decision(
                root,
                config,
                draft.title,
                context=draft.context,
                options=draft.options,
                assumptions=draft.assumptions,
                success_metrics=draft.success_metrics,
            )
            console.print(f"Created [bold]{record.id}[/bold]: {record.path}")


@app.command(name="export")
def export_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    format: str = typer.Option("html", "--format", help="Export format."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory."),
) -> None:
    """Export decisions."""
    if format != "html":
        raise typer.BadParameter("Only html export is supported.")
    root, config = _load(path)
    records = load_decisions(root, config)
    output_dir = output or (root / config.export_dir)
    pages = export_html(records, output_dir, config)
    console.print(f"Exported {len(pages)} HTML files to [bold]{output_dir}[/bold].")


@app.command()
def check(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    fail_on_overdue: bool = typer.Option(False, "--fail-on-overdue", help="Exit non-zero when decisions are overdue."),
    fail_under_score: bool = typer.Option(False, "--fail-under-score", help="Exit non-zero when records score below threshold."),
) -> None:
    """Validate decision records and print warnings."""
    root, config = _load(path)
    failed = _print_audit(root, config, fail_on_overdue=fail_on_overdue, fail_under_score=fail_under_score)
    if failed:
        raise typer.Exit(1)


@app.command()
def ui(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind. Defaults to localhost only."),
    port: int = typer.Option(8765, "--port", help="Port to bind."),
    open_browser: bool = typer.Option(False, "--open", help="Open the local UI in the default browser."),
) -> None:
    """Start the local browser UI."""
    import uvicorn

    from decisiontrail.web.app import create_web_app

    root, config = _load(path)
    ensure_template(root, config)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    console.print(f"Starting DecisionTrail UI at [bold]{url}[/bold]")
    console.print(f"Using local project path: [bold]{root}[/bold]")
    uvicorn.run(create_web_app(root), host=host, port=port)


@run_app.command("weekly-review")
def run_weekly_review(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Run the built-in weekly review report."""
    root, config = _load(path)
    report = weekly_review(load_decisions(root, config))
    _print_records("Decisions due for review", report["due"])
    _print_records("Decisions missing metrics", report["missing_metrics"])
    _print_assumption_rows("Assumptions not validated", report["unvalidated_assumptions"])


@run_app.command("audit")
def run_audit(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    fail_on_overdue: bool = typer.Option(False, "--fail-on-overdue", help="Exit non-zero when decisions are overdue."),
    fail_under_score: bool = typer.Option(False, "--fail-under-score", help="Exit non-zero when records score below threshold."),
) -> None:
    """Run the built-in structural and score audit."""
    root, config = _load(path)
    failed = _print_audit(root, config, fail_on_overdue=fail_on_overdue, fail_under_score=fail_under_score)
    if failed:
        raise typer.Exit(1)


@run_app.command("export-html")
def run_export_html(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory."),
) -> None:
    """Run the built-in HTML export action."""
    export_command(path=path, format="html", output=output)


@run_app.command("parse-meeting")
def run_parse_meeting(
    meeting_file: Path,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    write: bool = typer.Option(False, "--write", help="Write extracted drafts as decision records."),
) -> None:
    """Run the built-in meeting parser action."""
    parse_meeting(meeting_file=meeting_file, path=path, write=write)


def _print_records(title: str, records: list) -> None:
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Revisit")
    table.add_column("Title")
    for record in records:
        table.add_row(record.id, str(record.revisit_on or "-"), record.title)
    console.print(table)


def _print_assumption_rows(title: str, rows: list) -> None:
    table = Table(title=title)
    table.add_column("Decision")
    table.add_column("Status")
    table.add_column("Assumption")
    for item in rows:
        table.add_row(item.decision_id, item.status, item.text)
    console.print(table)


def _print_audit(
    root: Path,
    config,
    *,
    fail_on_overdue: bool = False,
    fail_under_score: bool = False,
) -> bool:
    records = load_decisions(root, config)
    issues = []
    low_scores = []
    overdue = weekly_review(records)["due"]

    for record in records:
        issues.extend(validate_record(record, records=records))
        result = score_decision(record)
        if result.score < config.score_threshold:
            low_scores.append(result)

    if issues:
        console.print("[bold]Audit warnings[/bold]")
        for issue in issues:
            console.print(f"- {issue}")
    else:
        console.print("No structural issues found.")

    if low_scores:
        table = Table(title=f"Records below score threshold ({config.score_threshold})")
        table.add_column("ID")
        table.add_column("Score", justify="right")
        table.add_column("Missing")
        for result in low_scores:
            table.add_row(result.decision_id, str(result.score), ", ".join(result.missing))
        console.print(table)

    unresolved = unvalidated_assumptions(records)
    if unresolved:
        _print_assumption_rows("Assumptions not validated", unresolved)

    failed = (fail_on_overdue and bool(overdue)) or (fail_under_score and bool(low_scores))
    if failed:
        console.print("[bold red]Audit failed because strict flags were enabled.[/bold red]")
    else:
        console.print("Audit completed with warning-only behavior.")
    return failed


def _print_link_rows(title: str, rows: list[tuple[str, str, str, str]]) -> None:
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Note")
    for row in rows:
        table.add_row(*row)
    console.print(table)


if __name__ == "__main__":
    app()
