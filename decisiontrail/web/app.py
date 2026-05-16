from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown import markdown

from decisiontrail.config import load_config
from decisiontrail.export import export_html
from decisiontrail.models import DecisionRecord, VALID_DIRECTIONS, VALID_RELATION_TYPES, VALID_STATUSES
from decisiontrail.parser import parse_meeting_text
from decisiontrail.relationships import (
    append_relation,
    backlinks,
    children_of,
    outgoing_relations,
    parse_relation_line,
    relation_errors,
)
from decisiontrail.review import (
    assumption_items,
    missing_metrics,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import create_decision, ensure_template, load_decision, load_decisions, write_decision
from decisiontrail.web.actions import delete_blockers, normalize_assumption, remove_relation_at, update_assumption_status
from decisiontrail.web.forms import (
    VALID_ASSUMPTION_STATUSES,
    DecisionFormData,
    form_to_create_kwargs,
    form_to_metadata_updates,
    record_to_form_data,
    validate_decision_form,
)


PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_web_app(root: Path) -> FastAPI:
    root = root.expanduser().resolve()
    app = FastAPI(title="DecisionTrail", docs_url=None, redoc_url=None)
    app.state.root = root
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        status: Annotated[str | None, Query()] = None,
        owner: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        config = load_config(root)
        records = load_decisions(root, config)
        filtered = filter_records(records, status=status, owner=owner)
        report = weekly_review(records)
        scores = [score_decision(record) for record in records]
        low_scores = [score for score in scores if score.score < config.score_threshold]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "root": root,
                "config": config,
                "records": records,
                "filtered_records": filtered,
                "report": report,
                "scores": {score.decision_id: score for score in scores},
                "low_scores": low_scores,
                "status_filter": status or "",
                "owner_filter": owner or "",
                "valid_statuses": sorted(VALID_STATUSES),
            },
        )

    @app.get("/audit", response_class=HTMLResponse)
    def audit(request: Request) -> HTMLResponse:
        config = load_config(root)
        records = load_decisions(root, config)
        scores = [score_decision(record) for record in records]
        report = weekly_review(records)
        return templates.TemplateResponse(
            request,
            "audit.html",
            {
                "root": root,
                "config": config,
                "records": records,
                "issues": [(record, issue) for record in records for issue in validate_record(record, records=records)],
                "low_scores": [score for score in scores if score.score < config.score_threshold],
                "due": report["due"],
                "missing_metrics": missing_metrics(records),
                "unvalidated_assumptions": unvalidated_assumptions(records),
                "review_candidates": report["review_candidates"],
            },
        )

    @app.post("/export-html", response_class=HTMLResponse)
    def export_html_from_ui(request: Request) -> HTMLResponse:
        config = load_config(root)
        records = load_decisions(root, config)
        output_dir = root / config.export_dir
        pages = export_html(records, output_dir, config)
        return templates.TemplateResponse(
            request,
            "export.html",
            {
                "root": root,
                "output_dir": output_dir,
                "pages": [
                    {
                        "path": page,
                        "name": page.name,
                        "href": f"/exports/{page.relative_to(output_dir).as_posix()}",
                    }
                    for page in pages
                ],
            },
        )

    @app.get("/exports/{filename:path}")
    def exported_file(filename: str) -> FileResponse:
        config = load_config(root)
        export_dir = (root / config.export_dir).resolve()
        candidate = (export_dir / filename).resolve()
        if not candidate.is_relative_to(export_dir) or not candidate.exists():
            raise HTTPException(status_code=404)
        return FileResponse(candidate)

    @app.get("/meeting-parser", response_class=HTMLResponse)
    def meeting_parser(request: Request) -> HTMLResponse:
        return render_meeting_parser(request, root)

    @app.post("/meeting-parser", response_class=HTMLResponse)
    def parse_meeting_from_ui(
        request: Request,
        meeting_text: Annotated[str, Form()] = "",
        action: Annotated[str, Form()] = "preview",
        selected: Annotated[list[int] | None, Form()] = None,
    ) -> HTMLResponse:
        config = load_config(root)
        drafts = parse_meeting_text(meeting_text, source_name="meeting form") if meeting_text.strip() else []
        errors = []
        created = []
        if not meeting_text.strip():
            errors.append("Meeting notes are required.")
        elif not drafts:
            errors.append("No decision candidates found.")
        elif action == "create":
            indexes = selected or []
            if not indexes:
                errors.append("Select at least one draft decision to create.")
            else:
                ensure_template(root, config)
                for index in indexes:
                    if index < 0 or index >= len(drafts):
                        continue
                    draft = drafts[index]
                    created.append(
                        create_decision(
                            root,
                            config,
                            draft.title,
                            context=draft.context,
                            options=draft.options,
                            assumptions=draft.assumptions,
                            success_metrics=draft.success_metrics,
                        )
                    )
        return render_meeting_parser(request, root, meeting_text, drafts, errors, created)

    @app.get("/decisions/new", response_class=HTMLResponse)
    def new_decision(request: Request) -> HTMLResponse:
        parent_id = request.query_params.get("parent", "")
        return render_form(request, root, DecisionFormData(parent_id=parent_id))

    @app.post("/decisions", response_class=HTMLResponse)
    def create_decision_from_form(
        request: Request,
        title: Annotated[str, Form()],
        owner: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "proposed",
        context: Annotated[str, Form()] = "",
        options: Annotated[str, Form()] = "",
        decision: Annotated[str, Form()] = "",
        rationale: Annotated[str, Form()] = "",
        assumptions: Annotated[str, Form()] = "",
        success_metrics: Annotated[str, Form()] = "",
        revisit_on: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = "en",
        direction: Annotated[str, Form()] = "auto",
        tags: Annotated[str, Form()] = "",
        parent_id: Annotated[str, Form()] = "",
        related_decisions: Annotated[str, Form()] = "",
    ) -> Response:
        data = DecisionFormData(
            title=title,
            owner=owner,
            status=status,
            context=context,
            options=options,
            decision=decision,
            rationale=rationale,
            assumptions=assumptions,
            success_metrics=success_metrics,
            revisit_on=revisit_on,
            language=language,
            direction=direction,
            tags=tags,
            parent_id=parent_id,
            related_decisions=related_decisions,
        )
        config = load_config(root)
        records = load_decisions(root, config)
        errors = validate_decision_form(data, {record.id for record in records})
        if errors:
            return render_form(request, root, data, errors, status_code=422)

        ensure_template(root, config)
        record = create_decision(root, config, data.title.strip(), **form_to_create_kwargs(data))
        return RedirectResponse(url=f"/decisions/{record.id}", status_code=303)

    @app.get("/decisions/{identifier}/edit", response_class=HTMLResponse)
    def edit_decision(request: Request, identifier: str) -> HTMLResponse:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        return render_edit_form(request, root, record, record_to_form_data(record))

    @app.post("/decisions/{identifier}/edit", response_class=HTMLResponse)
    def update_decision_from_form(
        request: Request,
        identifier: str,
        title: Annotated[str, Form()],
        owner: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "proposed",
        context: Annotated[str, Form()] = "",
        options: Annotated[str, Form()] = "",
        decision: Annotated[str, Form()] = "",
        rationale: Annotated[str, Form()] = "",
        assumptions: Annotated[str, Form()] = "",
        success_metrics: Annotated[str, Form()] = "",
        revisit_on: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = "en",
        direction: Annotated[str, Form()] = "auto",
        tags: Annotated[str, Form()] = "",
        parent_id: Annotated[str, Form()] = "",
        related_decisions: Annotated[str, Form()] = "",
        body: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        records = load_decisions(root, config)
        data = DecisionFormData(
            title=title,
            owner=owner,
            status=status,
            context=context,
            options=options,
            decision=decision,
            rationale=rationale,
            assumptions=assumptions,
            success_metrics=success_metrics,
            revisit_on=revisit_on,
            language=language,
            direction=direction,
            tags=tags,
            parent_id=parent_id,
            related_decisions=related_decisions,
            body=body,
        )
        errors = validate_decision_form(data, {item.id for item in records}, current_id=record.id)
        updates = form_to_metadata_updates(data)
        temp_metadata = {**record.metadata, **updates}
        temp_record = DecisionRecord(path=record.path, metadata=temp_metadata, body=body)
        temp_records = [item for item in records if item.id != record.id] + [temp_record]
        errors.extend(relation_errors(temp_record, temp_records))
        if errors:
            return render_edit_form(request, root, record, data, errors, status_code=422)

        record.metadata.update(updates)
        record.body = body
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}", status_code=303)

    @app.get("/decisions/{identifier}", response_class=HTMLResponse)
    def decision_detail(request: Request, identifier: str) -> HTMLResponse:
        return render_detail(request, root, identifier)

    @app.post("/decisions/{identifier}/status")
    def update_status_from_form(
        request: Request,
        identifier: str,
        status: Annotated[str, Form()],
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        if status not in VALID_STATUSES:
            return render_detail(request, root, identifier, [f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}."], 422)
        record.metadata["status"] = status
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}", status_code=303)

    @app.post("/decisions/{identifier}/assumptions/{index}")
    def update_assumption_from_form(
        request: Request,
        identifier: str,
        index: int,
        status: Annotated[str, Form()],
        note: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        try:
            update_assumption_status(record, index, status, note=note)
        except (IndexError, ValueError) as error:
            return render_detail(request, root, identifier, [str(error)], 422)
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}#assumptions", status_code=303)

    @app.post("/decisions/{identifier}/relations")
    def add_relation_from_form(
        request: Request,
        identifier: str,
        target_id: Annotated[str, Form()],
        relation_type: Annotated[str, Form()] = "related_to",
        note: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        records = load_decisions(root, config)
        record = load_decision(root, config, identifier)
        records_by_id = {item.id: item for item in records}
        errors = []
        if relation_type not in VALID_RELATION_TYPES:
            errors.append(f"Relation type must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}.")
        if target_id == record.id:
            errors.append("A decision cannot relate to itself.")
        if target_id not in records_by_id:
            errors.append(f"Related decision does not exist: {target_id}.")
        relation = parse_relation_line(f"{relation_type}: {target_id}" + (f" | {note}" if note.strip() else ""), source_id=record.id)
        if relation is None:
            errors.append("Relation could not be parsed.")
        if errors:
            return render_detail(request, root, identifier, errors, 422)
        append_relation(record, relation)
        relation_issues = relation_errors(record, [item for item in records if item.id != record.id] + [record])
        if relation_issues:
            return render_detail(request, root, identifier, relation_issues, 422)
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}#relationships", status_code=303)

    @app.post("/decisions/{identifier}/relations/remove")
    def remove_relation_from_form(
        request: Request,
        identifier: str,
        relation_index: Annotated[int, Form()],
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        try:
            remove_relation_at(record, relation_index)
        except IndexError as error:
            return render_detail(request, root, identifier, [str(error)], 422)
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}#relationships", status_code=303)

    @app.post("/decisions/{identifier}/review")
    def review_decision_from_form(
        request: Request,
        identifier: str,
        outcome: Annotated[str, Form()],
        reviewed_on: Annotated[str, Form()] = "",
        metric_note: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        review_date = reviewed_on.strip() or date.today().isoformat()
        try:
            date.fromisoformat(review_date)
        except ValueError:
            return render_detail(request, root, identifier, ["Review date must use ISO format: YYYY-MM-DD."], 422)
        record.metadata["outcome"] = outcome.strip()
        record.metadata["reviewed_on"] = review_date
        record.metadata["status"] = "reviewed"
        if metric_note.strip():
            notes = record.metadata.get("metric_notes") or []
            if not isinstance(notes, list):
                notes = [notes]
            notes.append({"reviewed_on": review_date, "note": metric_note.strip()})
            record.metadata["metric_notes"] = notes
        if "## Outcome Review" not in record.body:
            record.body = record.body.rstrip() + "\n\n## Outcome Review\n\n"
        record.body = record.body.rstrip() + f"\n\nReviewed on {review_date}: {outcome.strip()}\n"
        write_decision(record)
        return RedirectResponse(url=f"/decisions/{record.id}", status_code=303)

    @app.post("/decisions/{identifier}/delete")
    def delete_decision_from_form(
        request: Request,
        identifier: str,
        confirm_id: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        records = load_decisions(root, config)
        record = load_decision(root, config, identifier)
        errors = []
        if confirm_id.strip() != record.id:
            errors.append(f"Type {record.id} to confirm deletion.")
        blockers = delete_blockers(record, records)
        if blockers.children:
            errors.append("Delete blocked: this decision has child decisions.")
        if blockers.incoming_links:
            errors.append("Delete blocked: this decision has incoming backlinks.")
        if errors:
            return render_detail(request, root, identifier, errors, 422)
        record.path.unlink()
        return RedirectResponse(url="/", status_code=303)

    return app


def filter_records(records, *, status: str | None, owner: str | None):
    filtered = records
    if status:
        filtered = [record for record in filtered if record.status == status]
    if owner:
        filtered = [record for record in filtered if record.owner.lower() == owner.lower()]
    return filtered


def render_form(
    request: Request,
    root: Path,
    data: DecisionFormData,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "new.html",
        {
            "root": root,
            "data": data,
            "errors": errors or [],
            "records": load_decisions(root, load_config(root)),
            "valid_statuses": sorted(VALID_STATUSES),
            "valid_directions": ["auto", "ltr", "rtl"],
            "valid_relation_types": ["related_to", "depends_on", "blocks", "supersedes", "informs"],
        },
        status_code=status_code,
    )


def render_edit_form(
    request: Request,
    root: Path,
    record: DecisionRecord,
    data: DecisionFormData,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    records = load_decisions(root, load_config(root))
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "root": root,
            "record": record,
            "data": data,
            "errors": errors or [],
            "records": records,
            "valid_statuses": sorted(VALID_STATUSES),
            "valid_directions": ["auto", "ltr", "rtl"],
            "valid_relation_types": sorted(VALID_RELATION_TYPES),
        },
        status_code=status_code,
    )


def render_detail(
    request: Request,
    root: Path,
    identifier: str,
    action_errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    config = load_config(root)
    records = load_decisions(root, config)
    record = load_decision(root, config, identifier)
    records_by_id = {item.id: item for item in records}
    score = score_decision(record)
    assumptions = assumption_items([record])
    body_html = markdown(record.body, extensions=["fenced_code", "tables"])
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "root": root,
            "record": record,
            "records": records,
            "records_by_id": records_by_id,
            "parent": records_by_id.get(record.parent_id) if record.parent_id else None,
            "children": children_of(records, record.id),
            "outgoing_relations": outgoing_relations(record),
            "backlinks": backlinks(records, record.id),
            "delete_blockers": delete_blockers(record, records),
            "score": score,
            "assumptions": assumptions,
            "assumption_details": [normalize_assumption(item) for item in record.assumptions],
            "body_html": body_html,
            "issues": validate_record(record, records=records),
            "action_errors": action_errors or [],
            "today": date.today().isoformat(),
            "valid_statuses": sorted(VALID_STATUSES),
            "valid_relation_types": sorted(VALID_RELATION_TYPES),
            "assumption_statuses": sorted(VALID_ASSUMPTION_STATUSES),
        },
        status_code=status_code,
    )


def render_meeting_parser(
    request: Request,
    root: Path,
    meeting_text: str = "",
    drafts: list | None = None,
    errors: list[str] | None = None,
    created: list | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "meeting_parser.html",
        {
            "root": root,
            "meeting_text": meeting_text,
            "drafts": drafts or [],
            "errors": errors or [],
            "created": created or [],
        },
        status_code=status_code,
    )
