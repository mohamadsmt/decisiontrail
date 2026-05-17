from __future__ import annotations

import webbrowser
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from decisiontrail.assumptions import VALID_ASSUMPTION_STATUSES, update_assumption_status
from decisiontrail.config import dump_default_config, load_config
from decisiontrail.annotations import append_evidence, append_metric_update, evidence_items, metric_updates, remove_evidence_at
from decisiontrail.drafts import create_drafts_from_meeting, delete_draft, list_drafts, load_draft, promote_draft
from decisiontrail.export import export_html
from decisiontrail.graph import graph_json, graph_mermaid
from decisiontrail.models import (
    VALID_DECISION_TYPES,
    VALID_DIRECTIONS,
    VALID_EVIDENCE_TYPES,
    VALID_RELATION_TYPES,
    VALID_STATUSES,
    filter_records_by_tag,
    tag_labels,
)
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
    outcome_report,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import (
    copy_decision_record,
    create_decision,
    diff_decision_records,
    ensure_template,
    load_decision,
    load_decisions,
    load_history_snapshot,
    read_history_events,
    restore_history_snapshot,
    write_versioned_decision,
)
from decisiontrail.search import search_records
from decisiontrail.views import delete_user_view, list_views, resolve_view, save_user_view


app = typer.Typer(help="Local-first decision records for product, business, and strategy work.")
run_app = typer.Typer(help="Run built-in local actions.")
evidence_app = typer.Typer(help="Manage evidence references for a decision.")
metric_app = typer.Typer(help="Manage metric updates for a decision.")
assumptions_app = typer.Typer(help="Manage assumption validation plans.", invoke_without_command=True, no_args_is_help=False)
drafts_app = typer.Typer(help="Manage local draft decisions.")
views_app = typer.Typer(help="Manage private local saved views.")
app.add_typer(run_app, name="run")
app.add_typer(evidence_app, name="evidence")
app.add_typer(metric_app, name="metric")
app.add_typer(assumptions_app, name="assumptions")
app.add_typer(drafts_app, name="drafts")
app.add_typer(views_app, name="views")
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
                source="cli",
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
                source="cli",
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
    decision_type: str = typer.Option("general", "--type", help="Decision type template."),
    revisit_on: str = typer.Option("", "--revisit-on", help="ISO revisit date."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", help="Decision tag. Repeat to add multiple tags."),
    parent: str = typer.Option("", "--parent", help="Parent decision ID."),
    related: Optional[list[str]] = typer.Option(None, "--related", help="Typed relation, e.g. depends_on:DEC-2026-002."),
) -> None:
    """Create a new decision record."""
    if status not in VALID_STATUSES:
        raise typer.BadParameter(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    if direction not in VALID_DIRECTIONS:
        raise typer.BadParameter("Direction must be auto, ltr, or rtl.")
    if decision_type not in VALID_DECISION_TYPES:
        raise typer.BadParameter(f"Decision type must be one of: {', '.join(sorted(VALID_DECISION_TYPES))}")

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
        decision_type=decision_type,
        revisit_on=revisit_on,
        tags=tag or [],
        parent_id=parent,
        related_decisions=[relation_to_metadata(relation) for relation in related_decisions],
        source="cli",
    )
    console.print(f"Created [bold]{record.id}[/bold]: {record.path}")


@app.command()
def search(
    query: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter by owner."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag."),
    view: Optional[str] = typer.Option(None, "--view", help="Apply a saved or built-in view."),
    limit: int = typer.Option(20, "--limit", help="Maximum records to show."),
) -> None:
    """Search decision records across metadata and body."""
    root, config = _load(path)
    view_data = resolve_view(root, view or "")
    q = query
    due = False
    if view_data:
        q = q or view_data["q"]
        status = status or view_data["status"] or None
        owner = owner or view_data["owner"] or None
        tag = tag or view_data["tag"] or None
        due = bool(view_data["due"])
    hits = search_records(load_decisions(root, config), q, status=status, owner=owner, tag=tag, due=due, limit=limit)
    table = Table(title="Decision search")
    table.add_column("ID", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("Status", no_wrap=True)
    table.add_column("Tags")
    table.add_column("Title")
    for hit in hits:
        table.add_row(hit.record.id, str(hit.score), hit.record.status, ", ".join(tag_labels(hit.record)) or "-", hit.record.title)
    console.print(table)


@app.command(name="list")
def list_decisions(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter by owner."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag."),
    due_before: Optional[str] = typer.Option(None, "--due-before", help="Filter records due on or before an ISO date."),
) -> None:
    """List decision records."""
    root, config = _load(path)
    records = load_decisions(root, config)
    if status:
        records = [record for record in records if record.status == status]
    if owner:
        records = [record for record in records if record.owner.lower() == owner.lower()]
    records = filter_records_by_tag(records, tag)
    if due_before:
        target = date.fromisoformat(due_before)
        records = [record for record in records if record.revisit_on and record.revisit_on <= target]

    table = Table(title="Decision records")
    table.add_column("ID", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Owner", no_wrap=True)
    table.add_column("Parent", no_wrap=True)
    table.add_column("Revisit", no_wrap=True)
    table.add_column("Tags", no_wrap=True)
    table.add_column("Title")
    for record in records:
        table.add_row(
            record.id,
            record.status,
            record.owner or "-",
            record.parent_id or "-",
            str(record.revisit_on or "-"),
            ", ".join(tag_labels(record)) or "-",
            record.title,
        )
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


@app.command("review-inbox")
def review_inbox(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Show the operational decision review loop."""
    root, config = _load(path)
    records = load_decisions(root, config)
    _print_review_inbox(records)


@assumptions_app.callback(invoke_without_command=True)
def assumptions_callback(
    ctx: typer.Context,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """List tracked assumptions."""
    if ctx.invoked_subcommand is not None:
        return
    root, config = _load(path)
    _print_assumption_rows("Assumptions", assumption_items(load_decisions(root, config)), include_plan=True)


@assumptions_app.command("plan")
def assumptions_plan(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Show open assumptions with owners, due dates, signals, and evidence refs."""
    root, config = _load(path)
    _print_assumption_rows("Assumption validation plan", unvalidated_assumptions(load_decisions(root, config)), include_plan=True)


@assumptions_app.command("update")
def assumptions_update(
    identifier: str,
    index: int,
    status: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    owner: str = typer.Option("", "--owner", help="Validation owner. Empty clears the owner."),
    due_on: str = typer.Option("", "--due-on", help="ISO validation due date. Empty clears the date."),
    signal: str = typer.Option("", "--signal", help="Validation signal. Empty clears the signal."),
    evidence_ref: Optional[list[str]] = typer.Option(None, "--evidence-ref", help="Evidence ID to attach. Repeat to add multiple refs."),
    note: str = typer.Option("", "--note", help="Review or validation note."),
    reviewed_on: str = typer.Option("", "--reviewed-on", help="ISO reviewed date. Defaults to today."),
) -> None:
    """Update one assumption validation plan by zero-based index."""
    if status not in VALID_ASSUMPTION_STATUSES:
        raise typer.BadParameter(f"Status must be one of: {', '.join(sorted(VALID_ASSUMPTION_STATUSES))}.")
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    previous = copy_decision_record(record)
    try:
        update_assumption_status(
            record,
            index,
            status,
            note=note,
            reviewed_on=reviewed_on or None,
            owner=owner,
            due_on=due_on,
            signal=signal,
            evidence_refs=evidence_ref or [],
        )
    except (IndexError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    write_versioned_decision(root, config, previous, record, source="cli", action="assumption_updated")
    console.print(f"Updated assumption {index} on [bold]{record.id}[/bold].")


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
    previous = copy_decision_record(record)
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
    write_versioned_decision(root, config, previous, record, source="cli", action="reviewed")
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
    previous = copy_decision_record(source)
    append_relation(source, relation)
    issues = validate_record(source, records=temp_records)
    relation_issues = [issue for issue in issues if "related_decisions" in issue or "relation type" in issue]
    if relation_issues:
        raise typer.BadParameter("; ".join(relation_issues))
    write_versioned_decision(root, config, previous, source, source="cli", action="relation_added")
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
def history(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """Show version history for a decision."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    events = read_history_events(root, config, record.id)
    if not events:
        console.print(f"No version history found for [bold]{record.id}[/bold].")
        return

    table = Table(title=f"Version history for {record.id}")
    table.add_column("Version", no_wrap=True)
    table.add_column("Action", no_wrap=True)
    table.add_column("Changed at", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Changed fields")
    table.add_column("Snapshot")
    for event in events:
        table.add_row(
            f"v{event.get('version')}",
            str(event.get("action", "")),
            str(event.get("changed_at", "")),
            str(event.get("source", "")),
            ", ".join(str(field) for field in event.get("changed_fields", [])) or "-",
            str(event.get("snapshot", "")),
        )
    console.print(table)


@app.command(name="diff")
def diff_command(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    from_version: int = typer.Option(..., "--from", help="Source history version."),
    to_version: str = typer.Option("current", "--to", help="Target version number or current."),
) -> None:
    """Show a unified diff between a history snapshot and another version."""
    root, config = _load(path)
    current = load_decision(root, config, identifier)
    source = load_history_snapshot(root, config, current.id, from_version)
    target = current if to_version == "current" else load_history_snapshot(root, config, current.id, int(to_version))
    diff_text = diff_decision_records(source, target)
    console.print(diff_text or "No differences.")


@app.command()
def restore(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    version: int = typer.Option(..., "--version", help="History version to restore."),
    confirm_id: str = typer.Option("", "--confirm-id", help="Must exactly match the decision ID."),
) -> None:
    """Restore a history snapshot as a new current version."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    if confirm_id.strip() != record.id:
        raise typer.BadParameter(f"Type {record.id} with --confirm-id to restore.")
    result = restore_history_snapshot(root, config, record, version=version, source="cli")
    console.print(f"Restored [bold]{record.id}[/bold] from v{version} as v{result.version}.")


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
                source="cli",
            )
            console.print(f"Created [bold]{record.id}[/bold]: {record.path}")
    else:
        stored = create_drafts_from_meeting(root, meeting_file.read_text(encoding="utf-8"), source_name=meeting_file.name)
        for draft in stored:
            console.print(f"Saved draft [bold]{draft.id}[/bold]: {draft.title}")


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
def graph(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    format: str = typer.Option("mermaid", "--format", help="Output format: mermaid or json."),
) -> None:
    """Print the local decision graph."""
    root, config = _load(path)
    records = load_decisions(root, config)
    if format == "json":
        console.print(graph_json(records))
        return
    if format != "mermaid":
        raise typer.BadParameter("Graph format must be mermaid or json.")
    console.print(graph_mermaid(records))


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


@evidence_app.command("add")
def evidence_add(
    identifier: str,
    title: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    evidence_type: str = typer.Option("url", "--type", help="Evidence type."),
    ref: str = typer.Option("", "--ref", help="URL, local path, or external reference."),
    note: str = typer.Option("", "--note", help="Optional evidence note."),
    added_on: str = typer.Option("", "--added-on", help="ISO date. Defaults to today."),
    evidence_id: str = typer.Option("", "--evidence-id", help="Stable evidence ID. Defaults to the next EVD number."),
    assumption: Optional[int] = typer.Option(None, "--assumption", help="Zero-based assumption index to link."),
    metric: str = typer.Option("", "--metric", help="Metric name to link."),
) -> None:
    """Add an evidence reference to a decision."""
    if evidence_type not in VALID_EVIDENCE_TYPES:
        raise typer.BadParameter(f"Evidence type must be one of: {', '.join(sorted(VALID_EVIDENCE_TYPES))}.")
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    previous = copy_decision_record(record)
    try:
        item = append_evidence(
            record,
            title=title,
            evidence_type=evidence_type,
            ref=ref,
            note=note,
            added_on=added_on,
            evidence_id=evidence_id,
            assumption_index=assumption,
            metric_name=metric,
        )
    except (IndexError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    write_versioned_decision(root, config, previous, record, source="cli", action="evidence_added")
    console.print(f"Added evidence [bold]{item.get('id', '') or item['title']}[/bold] to {record.id}.")


@evidence_app.command("list")
def evidence_list(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """List evidence references for a decision."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    table = Table(title=f"Evidence for {record.id}")
    table.add_column("#", justify="right")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Reference")
    table.add_column("Links")
    table.add_column("Added")
    for index, item in enumerate(evidence_items(record)):
        table.add_row(
            str(index),
            str(item.get("id", "") or f"#{index}"),
            item["type"],
            item["title"],
            item["ref"] or item["note"],
            _format_evidence_links(item),
            item["added_on"],
        )
    console.print(table)


@evidence_app.command("remove")
def evidence_remove(
    identifier: str,
    index: int,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """Remove one evidence reference by zero-based index."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    previous = copy_decision_record(record)
    removed = remove_evidence_at(record, index)
    write_versioned_decision(root, config, previous, record, source="cli", action="evidence_removed")
    console.print(f"Removed evidence [bold]{removed['title']}[/bold] from {record.id}.")


@metric_app.command("add")
def metric_add(
    identifier: str,
    name: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    value: str = typer.Option("", "--value", help="Measured value."),
    measured_on: str = typer.Option("", "--measured-on", help="ISO date. Defaults to today."),
    note: str = typer.Option("", "--note", help="Optional metric note."),
) -> None:
    """Add a metric update to a decision."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    previous = copy_decision_record(record)
    item = append_metric_update(record, name=name, value=value, measured_on=measured_on, note=note)
    write_versioned_decision(root, config, previous, record, source="cli", action="metric_added")
    console.print(f"Added metric [bold]{item['name']}[/bold] to {record.id}.")


@metric_app.command("list")
def metric_list(
    identifier: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
) -> None:
    """List metric updates for a decision."""
    root, config = _load(path)
    record = load_decision(root, config, identifier)
    table = Table(title=f"Metric updates for {record.id}")
    table.add_column("Name")
    table.add_column("Value")
    table.add_column("Measured")
    table.add_column("Note")
    for item in metric_updates(record):
        table.add_row(item["name"], item["value"], item["measured_on"], item["note"])
    console.print(table)


@drafts_app.command("list")
def drafts_list(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """List local draft decisions."""
    root, _ = _load(path)
    table = Table(title="Draft decisions")
    table.add_column("ID")
    table.add_column("Source")
    table.add_column("Created")
    table.add_column("Title")
    for draft in list_drafts(root):
        table.add_row(draft.id, draft.source, draft.created_at, draft.title)
    console.print(table)


@drafts_app.command("show")
def drafts_show(draft_id: str, path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Show a local draft decision."""
    root, _ = _load(path)
    draft = load_draft(root, draft_id)
    console.print_json(data={
        "id": draft.id,
        "source": draft.source,
        "title": draft.title,
        "context": draft.context,
        "options": draft.options,
        "assumptions": draft.assumptions,
        "success_metrics": draft.success_metrics,
        "tags": draft.tags,
        "created_at": draft.created_at,
        "raw_excerpt": draft.raw_excerpt,
    })


@drafts_app.command("promote")
def drafts_promote(
    draft_id: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    owner: str = typer.Option("", "--owner", help="Decision owner."),
    status: str = typer.Option("proposed", "--status", help="Decision status."),
) -> None:
    """Promote a local draft into a real decision and remove the draft."""
    root, config = _load(path)
    record = promote_draft(root, config, draft_id, owner=owner, status=status)
    console.print(f"Promoted draft to [bold]{record.id}[/bold]: {record.path}")


@drafts_app.command("delete")
def drafts_delete(draft_id: str, path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Delete a local draft decision."""
    root, _ = _load(path)
    draft = delete_draft(root, draft_id)
    console.print(f"Deleted draft [bold]{draft.id}[/bold].")


@views_app.command("list")
def views_list(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """List built-in and private local saved views."""
    root, _ = _load(path)
    table = Table(title="Saved views")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Query")
    table.add_column("Status")
    table.add_column("Owner")
    table.add_column("Tag")
    table.add_column("Due")
    for view in list_views(root):
        table.add_row(
            view["name"],
            "built-in" if view.get("builtin") else "local",
            view["q"] or "-",
            view["status"] or "-",
            view["owner"] or "-",
            view["tag"] or "-",
            "yes" if view["due"] else "no",
        )
    console.print(table)


@views_app.command("save")
def views_save(
    name: str,
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project path."),
    q: str = typer.Option("", "--q", help="Search query."),
    status: str = typer.Option("", "--status", help="Status filter."),
    owner: str = typer.Option("", "--owner", help="Owner filter."),
    tag: str = typer.Option("", "--tag", help="Tag filter."),
    due: bool = typer.Option(False, "--due", help="Limit to due decisions."),
) -> None:
    """Save a private local view."""
    root, _ = _load(path)
    view = save_user_view(root, name=name, q=q, status=status, owner=owner, tag=tag, due=due)
    console.print(f"Saved local view [bold]{view['name']}[/bold].")


@views_app.command("delete")
def views_delete(name: str, path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Delete a private local view."""
    root, _ = _load(path)
    if not delete_user_view(root, name):
        raise typer.BadParameter(f"No local view found for: {name}")
    console.print(f"Deleted local view [bold]{name}[/bold].")


@run_app.command("weekly-review")
def run_weekly_review(path: Path = typer.Option(Path("."), "--path", "-p", help="Project path.")) -> None:
    """Run the built-in weekly review report."""
    root, config = _load(path)
    records = load_decisions(root, config)
    report = weekly_review(records)
    _print_records("Decisions due for review", report["due"])
    _print_records("Decisions missing metrics", report["missing_metrics"])
    _print_assumption_rows("Assumptions not validated", report["unvalidated_assumptions"], include_plan=True)
    _print_outcome_report(outcome_report(records))


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


def _print_assumption_rows(title: str, rows: list, *, include_plan: bool = False) -> None:
    table = Table(title=title)
    table.add_column("Decision")
    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("Assumption")
    table.add_column("Owner")
    table.add_column("Due")
    table.add_column("Signal")
    table.add_column("Evidence")
    for item in rows:
        table.add_row(
            item.decision_id,
            str(item.index),
            item.status,
            item.text,
            item.owner or "-",
            item.due_on or "-",
            item.signal or "-",
            ", ".join(item.evidence_refs or []) or "-",
        )
    console.print(table)


def _print_review_inbox(records: list) -> None:
    report = weekly_review(records)
    _print_records("Decisions due for review", report["due"])
    _print_records("Decisions missing metrics", report["missing_metrics"])
    _print_assumption_rows("Open assumptions", report["unvalidated_assumptions"], include_plan=True)
    _print_outcome_report(outcome_report(records))


def _print_outcome_report(report: dict) -> None:
    _print_records("Accepted but overdue", report["accepted_overdue"])
    _print_records("Supersede candidates", report["supersede_candidates"])
    table = Table(title="Decision outcome report")
    table.add_column("Signal")
    table.add_column("Count", justify="right")
    table.add_row("Decisions without success metrics", str(len(report["decisions_without_metrics"])))
    table.add_row("Open assumptions", str(len(report["open_assumptions"])))
    table.add_row("Validated assumptions", str(len(report["validated_assumptions"])))
    table.add_row("Invalidated assumptions", str(len(report["invalidated_assumptions"])))
    table.add_row("Timeline events", str(len(report["timeline"])))
    console.print(table)


def _format_evidence_links(item: dict) -> str:
    links = item.get("links") or []
    if not links:
        return "-"
    return ", ".join(f"{link.get('type')}:{link.get('target')}" for link in links)


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
