from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from decisiontrail.config import load_config
from decisiontrail.export import export_html as export_html_archive
from decisiontrail.models import (
    DecisionRecord,
    VALID_DIRECTIONS,
    VALID_RELATION_TYPES,
    VALID_STATUSES,
    contains_rtl_text,
)
from decisiontrail.parser import parse_meeting_text
from decisiontrail.relationships import (
    append_relation,
    backlinks,
    children_of,
    normalize_relation,
    outgoing_relations,
    parse_relation_line,
    parse_relation_lines,
    relation_errors,
    relation_to_metadata,
)
from decisiontrail.review import (
    missing_metrics,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import create_decision, ensure_template, load_decision, load_decisions, write_decision
from decisiontrail.web.actions import delete_blockers, remove_relation_at, update_assumption_status
from decisiontrail.web.forms import VALID_ASSUMPTION_STATUSES, parse_assumptions, split_lines


DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8766
DEFAULT_HTTP_PATH = "/mcp"


def resolve_root(path: str | Path | None = None) -> Path:
    """Resolve the DecisionTrail root from explicit path, environment, or cwd."""
    if path is not None and str(path).strip():
        candidate = Path(path)
    elif os.environ.get("DECISIONTRAIL_ROOT"):
        candidate = Path(os.environ["DECISIONTRAIL_ROOT"])
    else:
        candidate = Path.cwd()
    return candidate.expanduser().resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="decisiontrail-mcp",
        description="Run a local MCP server for DecisionTrail agent workflows.",
    )
    parser.add_argument("--path", default=None, help="DecisionTrail project path. Defaults to DECISIONTRAIL_ROOT or cwd.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to run. Defaults to stdio.",
    )
    parser.add_argument("--host", default=DEFAULT_HTTP_HOST, help="HTTP host for streamable-http transport.")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP port for streamable-http transport.")
    parser.add_argument("--path-prefix", default=DEFAULT_HTTP_PATH, help="HTTP MCP path for streamable-http transport.")
    return parser.parse_args(argv)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _parse_iso_date(value: str | None, *, field_name: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ValueError(f"{field_name} must use ISO format: YYYY-MM-DD.") from error


def _validate_status(status: str) -> str:
    status = status.strip() or "proposed"
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}.")
    return status


def _validate_direction(direction: str) -> str:
    direction = direction.strip() or "auto"
    if direction not in VALID_DIRECTIONS:
        raise ValueError("Direction must be auto, ltr, or rtl.")
    return direction


def _has_rtl_decision_signal(title: str, context: str) -> bool:
    return contains_rtl_text(title) or contains_rtl_text(context)


def _infer_language_and_direction(
    title: str,
    context: str,
    *,
    language: str | None,
    direction: str | None,
) -> tuple[str, str]:
    has_rtl = _has_rtl_decision_signal(title, context)
    inferred_language = language.strip() if language and language.strip() else ("fa" if has_rtl else "en")
    inferred_direction = direction.strip() if direction and direction.strip() else ("rtl" if has_rtl else "auto")
    return inferred_language, _validate_direction(inferred_direction)


def _normalize_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return split_lines(value)
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_assumption_list(value: Any) -> list[dict[str, str]] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return parse_assumptions(value)

    assumptions: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            status = str(item.get("status", "") or "unvalidated").strip()
            if status not in VALID_ASSUMPTION_STATUSES:
                raise ValueError(f"Assumption status must be one of: {', '.join(sorted(VALID_ASSUMPTION_STATUSES))}.")
            normalized = {"text": text, "status": status}
            note = str(item.get("note", "") or "").strip()
            reviewed_on = str(item.get("reviewed_on", "") or "").strip()
            if note:
                normalized["note"] = note
            if reviewed_on:
                _parse_iso_date(reviewed_on, field_name="reviewed_on")
                normalized["reviewed_on"] = reviewed_on
            assumptions.append(normalized)
        else:
            assumptions.extend(parse_assumptions(str(item)))
    return assumptions


def _normalize_relation_list(
    value: Any,
    *,
    known_ids: set[str],
    source_id: str = "",
) -> list[dict[str, str]] | None:
    if value is None:
        return None

    if isinstance(value, str):
        relations = parse_relation_lines(value, source_id=source_id)
    else:
        relations = []
        for item in value:
            relation = normalize_relation(item, source_id=source_id)
            if relation:
                relations.append(relation)

    for relation in relations:
        if relation.relation_type not in VALID_RELATION_TYPES:
            raise ValueError(f"Relation type must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}.")
        if source_id and relation.target_id == source_id:
            raise ValueError("A decision cannot relate to itself.")
        if relation.target_id not in known_ids:
            raise ValueError(f"Related decision does not exist: {relation.target_id}.")
    return [relation_to_metadata(relation) for relation in relations]


def _resolve_output_path(root: Path, output: str | Path | None, default_name: str) -> Path:
    if output is None or not str(output).strip():
        return root / default_name
    candidate = Path(output)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.expanduser().resolve()


class DecisionTrailMCPService:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = resolve_root(root)

    @property
    def config(self):
        return load_config(self.root)

    def schema(self) -> dict[str, Any]:
        return {
            "statuses": sorted(VALID_STATUSES),
            "directions": sorted(VALID_DIRECTIONS),
            "relation_types": sorted(VALID_RELATION_TYPES),
            "assumption_statuses": sorted(VALID_ASSUMPTION_STATUSES),
            "required_metadata": ["id", "title", "status", "date"],
            "recommended_fields": [
                "owner",
                "context",
                "options",
                "decision",
                "rationale",
                "assumptions",
                "success_metrics",
                "revisit_on",
            ],
            "root": str(self.root),
            "config": _jsonable(self.config),
        }

    def workflow_guide(self) -> str:
        return (
            "Use DecisionTrail tools to convert rough decisions into durable records. "
            "First inspect project_status and search/list existing decisions for context. "
            "When capturing a rough decision, infer context, options, rationale, assumptions, "
            "success metrics, revisit date, language, and direction from the user input. "
            "Write directly with record_decision, then call audit_decisions and return the "
            "record ID, score, warnings, and follow-up gaps to the user. Preserve existing "
            "record paths on update_decision. Use add_relation for dependencies and review_decision "
            "when measured outcomes are known."
        )

    def project_status(self) -> dict[str, Any]:
        records = load_decisions(self.root, self.config)
        report = weekly_review(records)
        scores = [score_decision(record) for record in records]
        low_scores = [score for score in scores if score.score < self.config.score_threshold]
        return {
            "root": str(self.root),
            "config": _jsonable(self.config),
            "decision_count": len(records),
            "due_count": len(report["due"]),
            "missing_metrics_count": len(report["missing_metrics"]),
            "unvalidated_assumption_count": len(report["unvalidated_assumptions"]),
            "low_score_count": len(low_scores),
            "score_threshold": self.config.score_threshold,
        }

    def list_decisions(
        self,
        *,
        status: str | None = None,
        owner: str | None = None,
        due_before: str | None = None,
    ) -> dict[str, Any]:
        records = load_decisions(self.root, self.config)
        if status:
            status = _validate_status(status)
            records = [record for record in records if record.status == status]
        if owner:
            records = [record for record in records if record.owner.lower() == owner.lower()]
        if due_before:
            target = _parse_iso_date(due_before, field_name="due_before")
            records = [record for record in records if record.revisit_on and record.revisit_on <= target]
        return {"records": [self._record_summary(record) for record in records]}

    def get_decision(self, identifier: str) -> dict[str, Any]:
        records = load_decisions(self.root, self.config)
        record = load_decision(self.root, self.config, identifier)
        return self._record_detail(record, records)

    def search_decisions(
        self,
        query: str,
        *,
        status: str | None = None,
        owner: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        query = query.strip().lower()
        records = self.list_decisions(status=status, owner=owner)["records"]
        matches = []
        for summary in records:
            record = load_decision(self.root, self.config, summary["id"])
            haystack = " ".join(
                [
                    record.id,
                    record.title,
                    record.status,
                    record.owner,
                    str(record.metadata.get("context", "") or ""),
                    str(record.metadata.get("decision", "") or ""),
                    " ".join(str(tag) for tag in record.tags),
                    record.body,
                ]
            ).lower()
            if not query or query in haystack:
                matches.append(summary)
            if len(matches) >= limit:
                break
        return {"query": query, "records": matches}

    def record_decision(
        self,
        *,
        title: str,
        owner: str = "",
        status: str = "proposed",
        context: str = "",
        options: Any = None,
        decision: str = "",
        rationale: Any = None,
        assumptions: Any = None,
        success_metrics: Any = None,
        revisit_on: str = "",
        language: str | None = None,
        direction: str | None = None,
        tags: Any = None,
        parent_id: str = "",
        related_decisions: Any = None,
        created_on: str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Title is required.")

        config = self.config
        ensure_template(self.root, config)
        records = load_decisions(self.root, config)
        known_ids = {record.id for record in records}
        if parent_id and parent_id not in known_ids:
            raise ValueError(f"Parent decision does not exist: {parent_id}.")

        revisit_value = revisit_on.strip()
        _parse_iso_date(revisit_value, field_name="revisit_on")
        normalized_language, normalized_direction = _infer_language_and_direction(
            title,
            context,
            language=language,
            direction=direction,
        )
        related = _normalize_relation_list(related_decisions, known_ids=known_ids) or []
        record = create_decision(
            self.root,
            config,
            title,
            status=_validate_status(status),
            owner=owner.strip(),
            created_on=_parse_iso_date(created_on, field_name="created_on"),
            context=context.strip(),
            options=_normalize_string_list(options) or [],
            decision=decision.strip(),
            rationale=_normalize_string_list(rationale) or [],
            assumptions=_normalize_assumption_list(assumptions) or [],
            success_metrics=_normalize_string_list(success_metrics) or [],
            revisit_on=revisit_value,
            language=normalized_language,
            direction=normalized_direction,
            tags=_normalize_string_list(tags) or [],
            parent_id=parent_id.strip(),
            related_decisions=related,
        )
        return self._write_result("created", record)

    def update_decision(
        self,
        identifier: str,
        *,
        title: str | None = None,
        owner: str | None = None,
        status: str | None = None,
        context: str | None = None,
        options: Any = None,
        decision: str | None = None,
        rationale: Any = None,
        assumptions: Any = None,
        success_metrics: Any = None,
        revisit_on: str | None = None,
        language: str | None = None,
        direction: str | None = None,
        tags: Any = None,
        parent_id: str | None = None,
        related_decisions: Any = None,
        body: str | None = None,
        created_on: str | None = None,
    ) -> dict[str, Any]:
        config = self.config
        records = load_decisions(self.root, config)
        record = load_decision(self.root, config, identifier)
        known_ids = {item.id for item in records}

        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("Title is required.")
            record.metadata["title"] = title
        if owner is not None:
            record.metadata["owner"] = owner.strip()
        if status is not None:
            record.metadata["status"] = _validate_status(status)
        if context is not None:
            record.metadata["context"] = context.strip()
        if options is not None:
            record.metadata["options"] = _normalize_string_list(options) or []
        if decision is not None:
            record.metadata["decision"] = decision.strip()
        if rationale is not None:
            record.metadata["rationale"] = _normalize_string_list(rationale) or []
        if assumptions is not None:
            record.metadata["assumptions"] = _normalize_assumption_list(assumptions) or []
        if success_metrics is not None:
            record.metadata["success_metrics"] = _normalize_string_list(success_metrics) or []
        if revisit_on is not None:
            _parse_iso_date(revisit_on, field_name="revisit_on")
            record.metadata["revisit_on"] = revisit_on.strip()
        if language is not None:
            record.metadata["language"] = language.strip() or "en"
        if direction is not None:
            record.metadata["direction"] = _validate_direction(direction)
        if tags is not None:
            record.metadata["tags"] = _normalize_string_list(tags) or []
        if parent_id is not None:
            parent_id = parent_id.strip()
            if parent_id == record.id:
                raise ValueError("A decision cannot be its own parent.")
            if parent_id and parent_id not in known_ids:
                raise ValueError(f"Parent decision does not exist: {parent_id}.")
            record.metadata["parent_id"] = parent_id
        if related_decisions is not None:
            record.metadata["related_decisions"] = _normalize_relation_list(
                related_decisions,
                known_ids=known_ids,
                source_id=record.id,
            ) or []
        if body is not None:
            record.body = body
        if created_on is not None:
            parsed = _parse_iso_date(created_on, field_name="created_on")
            record.metadata["date"] = parsed.isoformat() if parsed else ""

        updated_records = [item for item in records if item.id != record.id] + [record]
        issues = relation_errors(record, updated_records)
        if issues:
            raise ValueError("; ".join(issues))
        write_decision(record)
        return self._write_result("updated", record)

    def update_status(self, identifier: str, status: str) -> dict[str, Any]:
        config = self.config
        record = load_decision(self.root, config, identifier)
        record.metadata["status"] = _validate_status(status)
        write_decision(record)
        return self._write_result("updated", record)

    def add_relation(
        self,
        identifier: str,
        target_id: str,
        *,
        relation_type: str = "related_to",
        note: str = "",
    ) -> dict[str, Any]:
        config = self.config
        records = load_decisions(self.root, config)
        record = load_decision(self.root, config, identifier)
        records_by_id = {item.id: item for item in records}
        if relation_type not in VALID_RELATION_TYPES:
            raise ValueError(f"Relation type must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}.")
        if target_id == record.id:
            raise ValueError("A decision cannot relate to itself.")
        if target_id not in records_by_id:
            raise ValueError(f"Related decision does not exist: {target_id}.")
        relation = parse_relation_line(f"{relation_type}: {target_id}" + (f" | {note}" if note.strip() else ""), source_id=record.id)
        if relation is None:
            raise ValueError("Relation could not be parsed.")
        append_relation(record, relation)
        issues = relation_errors(record, [item for item in records if item.id != record.id] + [record])
        if issues:
            raise ValueError("; ".join(issues))
        write_decision(record)
        return self._write_result("updated", record)

    def remove_relation(self, identifier: str, relation_index: int) -> dict[str, Any]:
        config = self.config
        record = load_decision(self.root, config, identifier)
        remove_relation_at(record, relation_index)
        write_decision(record)
        return self._write_result("updated", record)

    def update_assumption(
        self,
        identifier: str,
        assumption_index: int,
        status: str,
        *,
        note: str = "",
        reviewed_on: str | None = None,
    ) -> dict[str, Any]:
        if reviewed_on:
            _parse_iso_date(reviewed_on, field_name="reviewed_on")
        config = self.config
        record = load_decision(self.root, config, identifier)
        update_assumption_status(record, assumption_index, status, note=note, reviewed_on=reviewed_on)
        write_decision(record)
        return self._write_result("updated", record)

    def review_decision(
        self,
        identifier: str,
        *,
        outcome: str,
        reviewed_on: str = "",
        metric_note: str = "",
    ) -> dict[str, Any]:
        outcome = outcome.strip()
        if not outcome:
            raise ValueError("Outcome is required.")
        review_date = reviewed_on.strip() or date.today().isoformat()
        _parse_iso_date(review_date, field_name="reviewed_on")
        config = self.config
        record = load_decision(self.root, config, identifier)
        record.metadata["outcome"] = outcome
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
        record.body = record.body.rstrip() + f"\n\nReviewed on {review_date}: {outcome}\n"
        write_decision(record)
        return self._write_result("reviewed", record)

    def parse_meeting(
        self,
        meeting_text: str,
        *,
        source_name: str = "agent input",
        write: bool = False,
        selected_indexes: list[int] | None = None,
        owner: str = "",
        status: str = "proposed",
    ) -> dict[str, Any]:
        drafts = parse_meeting_text(meeting_text, source_name=source_name)
        draft_data = [_jsonable(asdict(draft)) for draft in drafts]
        if not write:
            return {"drafts": draft_data, "created": []}

        config = self.config
        ensure_template(self.root, config)
        indexes = selected_indexes if selected_indexes is not None else list(range(len(drafts)))
        created = []
        for index in indexes:
            if index < 0 or index >= len(drafts):
                raise ValueError(f"Draft index is out of range: {index}.")
            draft = drafts[index]
            language, direction = _infer_language_and_direction(draft.title, draft.context, language=None, direction=None)
            record = create_decision(
                self.root,
                config,
                draft.title,
                owner=owner.strip(),
                status=_validate_status(status),
                context=draft.context,
                options=draft.options,
                assumptions=_normalize_assumption_list(draft.assumptions) or [],
                success_metrics=draft.success_metrics,
                language=language,
                direction=direction,
            )
            created.append(self._record_summary(record))
        return {"drafts": draft_data, "created": created}

    def audit_decisions(
        self,
        *,
        fail_on_overdue: bool = False,
        fail_under_score: bool = False,
    ) -> dict[str, Any]:
        records = load_decisions(self.root, self.config)
        report = weekly_review(records)
        scores = [score_decision(record) for record in records]
        low_scores = [score for score in scores if score.score < self.config.score_threshold]
        issues = [issue for record in records for issue in validate_record(record, records=records)]
        failed = (fail_on_overdue and bool(report["due"])) or (fail_under_score and bool(low_scores))
        return {
            "issues": issues,
            "low_scores": [_jsonable(score) for score in low_scores],
            "due": [self._record_summary(record) for record in report["due"]],
            "missing_metrics": [self._record_summary(record) for record in missing_metrics(records)],
            "unvalidated_assumptions": [_jsonable(item) for item in unvalidated_assumptions(records)],
            "failed": failed,
            "warn_only": not failed,
        }

    def export_html(self, *, output: str | None = None) -> dict[str, Any]:
        config = self.config
        output_dir = _resolve_output_path(self.root, output, config.export_dir)
        pages = export_html_archive(load_decisions(self.root, config), output_dir, config)
        return {"output_dir": str(output_dir), "pages": [str(page) for page in pages], "page_count": len(pages)}

    def delete_decision(self, identifier: str, *, confirm_id: str = "") -> dict[str, Any]:
        config = self.config
        records = load_decisions(self.root, config)
        record = load_decision(self.root, config, identifier)
        blockers = delete_blockers(record, records)
        errors = []
        if confirm_id.strip() != record.id:
            errors.append(f"Type {record.id} to confirm deletion.")
        if blockers.children:
            errors.append("Delete blocked: this decision has child decisions.")
        if blockers.incoming_links:
            errors.append("Delete blocked: this decision has incoming backlinks.")
        if errors:
            return {
                "deleted": False,
                "id": record.id,
                "path": str(record.path),
                "errors": errors,
                "blockers": self._delete_blockers(blockers),
            }
        record.path.unlink()
        return {"deleted": True, "id": record.id, "path": str(record.path), "errors": [], "blockers": self._delete_blockers(blockers)}

    def _write_result(self, action: str, record: DecisionRecord) -> dict[str, Any]:
        records = load_decisions(self.root, self.config)
        return {
            "action": action,
            "record": self._record_detail(record, records),
            "path": str(record.path),
            "score": _jsonable(score_decision(record)),
            "issues": validate_record(record, records=records),
        }

    def _record_summary(self, record: DecisionRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "title": record.title,
            "status": record.status,
            "owner": record.owner,
            "date": _jsonable(record.decision_date),
            "revisit_on": _jsonable(record.revisit_on),
            "language": record.language,
            "direction": record.direction,
            "parent_id": record.parent_id,
            "tags": _jsonable(record.tags),
            "path": str(record.path),
            "score": score_decision(record).score,
        }

    def _record_detail(self, record: DecisionRecord, records: list[DecisionRecord]) -> dict[str, Any]:
        records_by_id = {item.id: item for item in records}
        parent = records_by_id.get(record.parent_id) if record.parent_id else None
        return {
            **self._record_summary(record),
            "metadata": _jsonable(record.metadata),
            "body": record.body,
            "scorecard": _jsonable(score_decision(record)),
            "issues": validate_record(record, records=records),
            "parent": self._record_summary(parent) if parent else None,
            "children": [self._record_summary(child) for child in children_of(records, record.id)],
            "outgoing_relations": [_jsonable(relation) for relation in outgoing_relations(record)],
            "backlinks": [_jsonable(relation) for relation in backlinks(records, record.id)],
        }

    def _delete_blockers(self, blockers) -> dict[str, Any]:
        return {
            "children": [self._record_summary(record) for record in blockers.children],
            "incoming_links": [_jsonable(relation) for relation in blockers.incoming_links],
        }


def create_mcp_server(
    service: DecisionTrailMCPService | None = None,
    *,
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    path_prefix: str = DEFAULT_HTTP_PATH,
    json_response: bool = False,
    stateless_http: bool = False,
):
    from mcp.server.fastmcp import FastMCP

    active_service = service or DecisionTrailMCPService()
    mcp = FastMCP(
        "DecisionTrail",
        host=host,
        port=port,
        streamable_http_path=path_prefix,
        json_response=json_response,
        stateless_http=stateless_http,
    )

    @mcp.resource("decisiontrail://schema")
    def decisiontrail_schema() -> str:
        """DecisionTrail schema and accepted values."""
        return json.dumps(active_service.schema(), ensure_ascii=False, indent=2)

    @mcp.resource("decisiontrail://workflow-guide")
    def decisiontrail_workflow_guide() -> str:
        """Agent workflow guidance for DecisionTrail records."""
        return active_service.workflow_guide()

    @mcp.prompt()
    def capture_decision_from_rough(rough_decision: str, owner: str = "", status: str = "proposed") -> str:
        """Guide an agent through direct-write capture of a rough decision."""
        return (
            "Capture this rough decision in DecisionTrail.\n"
            f"Rough decision:\n{rough_decision}\n\n"
            f"Default owner: {owner or 'infer or leave blank'}\n"
            f"Default status: {status or 'proposed'}\n\n"
            "Steps:\n"
            "1. Call project_status and search_decisions/list_decisions for nearby context.\n"
            "2. Infer title, context, options, selected decision, rationale, assumptions, success metrics, "
            "revisit_on, language, direction, tags, parent_id, and related_decisions.\n"
            "3. Call record_decision directly.\n"
            "4. Call audit_decisions and report the record ID, score, issues, and follow-up gaps."
        )

    @mcp.tool()
    def project_status() -> dict[str, Any]:
        """Summarize the current DecisionTrail project."""
        return active_service.project_status()

    @mcp.tool()
    def list_decisions(status: str | None = None, owner: str | None = None, due_before: str | None = None) -> dict[str, Any]:
        """List decision records with optional filters."""
        return active_service.list_decisions(status=status, owner=owner, due_before=due_before)

    @mcp.tool()
    def get_decision(identifier: str) -> dict[str, Any]:
        """Read one decision with metadata, body, relationships, score, and validation issues."""
        return active_service.get_decision(identifier)

    @mcp.tool()
    def search_decisions(query: str, status: str | None = None, owner: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search decision records by text across metadata and body."""
        return active_service.search_decisions(query, status=status, owner=owner, limit=limit)

    @mcp.tool()
    def record_decision(
        title: str,
        owner: str = "",
        status: str = "proposed",
        context: str = "",
        options: list[str] | None = None,
        decision: str = "",
        rationale: list[str] | None = None,
        assumptions: list[Any] | None = None,
        success_metrics: list[str] | None = None,
        revisit_on: str = "",
        language: str | None = None,
        direction: str | None = None,
        tags: list[str] | None = None,
        parent_id: str = "",
        related_decisions: list[Any] | None = None,
        created_on: str | None = None,
    ) -> dict[str, Any]:
        """Create a decision record directly from structured or inferred fields."""
        return active_service.record_decision(
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
            created_on=created_on,
        )

    @mcp.tool()
    def update_decision(
        identifier: str,
        title: str | None = None,
        owner: str | None = None,
        status: str | None = None,
        context: str | None = None,
        options: list[str] | None = None,
        decision: str | None = None,
        rationale: list[str] | None = None,
        assumptions: list[Any] | None = None,
        success_metrics: list[str] | None = None,
        revisit_on: str | None = None,
        language: str | None = None,
        direction: str | None = None,
        tags: list[str] | None = None,
        parent_id: str | None = None,
        related_decisions: list[Any] | None = None,
        body: str | None = None,
        created_on: str | None = None,
    ) -> dict[str, Any]:
        """Partially update an existing decision without changing its file path."""
        return active_service.update_decision(
            identifier,
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
            created_on=created_on,
        )

    @mcp.tool()
    def update_status(identifier: str, status: str) -> dict[str, Any]:
        """Update a decision status."""
        return active_service.update_status(identifier, status)

    @mcp.tool()
    def add_relation(identifier: str, target_id: str, relation_type: str = "related_to", note: str = "") -> dict[str, Any]:
        """Add a typed outgoing relation from one decision to another."""
        return active_service.add_relation(identifier, target_id, relation_type=relation_type, note=note)

    @mcp.tool()
    def remove_relation(identifier: str, relation_index: int) -> dict[str, Any]:
        """Remove one outgoing relation by zero-based index."""
        return active_service.remove_relation(identifier, relation_index)

    @mcp.tool()
    def update_assumption(
        identifier: str,
        assumption_index: int,
        status: str,
        note: str = "",
        reviewed_on: str | None = None,
    ) -> dict[str, Any]:
        """Update one assumption status by zero-based index."""
        return active_service.update_assumption(identifier, assumption_index, status, note=note, reviewed_on=reviewed_on)

    @mcp.tool()
    def review_decision(identifier: str, outcome: str, reviewed_on: str = "", metric_note: str = "") -> dict[str, Any]:
        """Record an outcome review and mark a decision reviewed."""
        return active_service.review_decision(identifier, outcome=outcome, reviewed_on=reviewed_on, metric_note=metric_note)

    @mcp.tool()
    def parse_meeting(
        meeting_text: str,
        source_name: str = "agent input",
        write: bool = False,
        selected_indexes: list[int] | None = None,
        owner: str = "",
        status: str = "proposed",
    ) -> dict[str, Any]:
        """Parse meeting notes into draft decisions, optionally writing selected drafts."""
        return active_service.parse_meeting(
            meeting_text,
            source_name=source_name,
            write=write,
            selected_indexes=selected_indexes,
            owner=owner,
            status=status,
        )

    @mcp.tool()
    def audit_decisions(fail_on_overdue: bool = False, fail_under_score: bool = False) -> dict[str, Any]:
        """Run structural, score, overdue, metrics, and assumption checks."""
        return active_service.audit_decisions(fail_on_overdue=fail_on_overdue, fail_under_score=fail_under_score)

    @mcp.tool()
    def export_html(output: str | None = None) -> dict[str, Any]:
        """Export local static HTML pages."""
        return active_service.export_html(output=output)

    @mcp.tool()
    def delete_decision(identifier: str, confirm_id: str = "") -> dict[str, Any]:
        """Delete an unreferenced decision only when confirm_id exactly matches the decision ID."""
        return active_service.delete_decision(identifier, confirm_id=confirm_id)

    return mcp


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    service = DecisionTrailMCPService(resolve_root(args.path))
    mcp = create_mcp_server(
        service,
        host=args.host,
        port=args.port,
        path_prefix=args.path_prefix,
        json_response=args.transport == "streamable-http",
        stateless_http=args.transport == "streamable-http",
    )
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
