from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown import markdown

from decisiontrail.config import load_config
from decisiontrail.models import VALID_DIRECTIONS, VALID_STATUSES
from decisiontrail.review import (
    assumption_items,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import create_decision, ensure_template, load_decision, load_decisions, write_decision
from decisiontrail.web.forms import DecisionFormData, form_to_create_kwargs, validate_decision_form


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

    @app.get("/decisions/new", response_class=HTMLResponse)
    def new_decision(request: Request) -> HTMLResponse:
        return render_form(request, root, DecisionFormData())

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
        )
        errors = validate_decision_form(data)
        if errors:
            return render_form(request, root, data, errors, status_code=422)

        config = load_config(root)
        ensure_template(root, config)
        record = create_decision(root, config, data.title.strip(), **form_to_create_kwargs(data))
        return RedirectResponse(url=f"/decisions/{record.id}", status_code=303)

    @app.get("/decisions/{identifier}", response_class=HTMLResponse)
    def decision_detail(request: Request, identifier: str) -> HTMLResponse:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        score = score_decision(record)
        assumptions = assumption_items([record])
        body_html = markdown(record.body, extensions=["fenced_code", "tables"])
        return templates.TemplateResponse(
            request,
            "detail.html",
            {
                "root": root,
                "record": record,
                "score": score,
                "assumptions": assumptions,
                "body_html": body_html,
                "issues": validate_record(record),
                "today": date.today().isoformat(),
            },
        )

    @app.post("/decisions/{identifier}/review")
    def review_decision_from_form(
        identifier: str,
        outcome: Annotated[str, Form()],
        reviewed_on: Annotated[str, Form()] = "",
        metric_note: Annotated[str, Form()] = "",
    ) -> Response:
        config = load_config(root)
        record = load_decision(root, config, identifier)
        review_date = reviewed_on.strip() or date.today().isoformat()
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
            "valid_statuses": sorted(VALID_STATUSES),
            "valid_directions": ["auto", "ltr", "rtl"],
        },
        status_code=status_code,
    )
