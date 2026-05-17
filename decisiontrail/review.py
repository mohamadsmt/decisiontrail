from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from decisiontrail.assumptions import normalize_assumption
from decisiontrail.models import (
    DecisionRecord,
    VALID_DIRECTIONS,
    VALID_STATUSES,
    as_date,
    contains_rtl_text,
    is_present,
)
from decisiontrail.relationships import relation_errors


@dataclass(frozen=True)
class ScoreResult:
    decision_id: str
    title: str
    score: int
    passed: list[str]
    missing: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class AssumptionItem:
    decision_id: str
    title: str
    index: int
    text: str
    status: str
    owner: str = ""
    due_on: str = ""
    signal: str = ""
    evidence_refs: list[str] | None = None
    note: str = ""
    reviewed_on: str = ""


def is_overdue(record: DecisionRecord, today: date | None = None) -> bool:
    current_date = today or date.today()
    if record.status in {"reviewed", "superseded", "rejected"}:
        return False
    if is_present(record.outcome):
        return False
    revisit_on = record.revisit_on
    return bool(revisit_on and revisit_on <= current_date)


def score_decision(record: DecisionRecord, today: date | None = None) -> ScoreResult:
    checks: list[tuple[str, int, bool]] = [
        ("required metadata", 10, all(is_present(record.metadata.get(key)) for key in ["id", "title", "status", "date"])),
        ("owner", 10, is_present(record.owner)),
        ("context", 15, is_present(record.metadata.get("context"))),
        ("options", 15, len(record.options) >= 2),
        ("decision and rationale", 20, is_present(record.metadata.get("decision")) and bool(record.rationale)),
        ("assumptions", 10, bool(record.assumptions)),
        ("success metrics", 10, bool(record.success_metrics)),
        ("revisit date", 10, record.revisit_on is not None),
    ]

    score = 0
    passed: list[str] = []
    missing: list[str] = []
    for label, weight, ok in checks:
        if ok:
            score += weight
            passed.append(label)
        else:
            missing.append(label)

    warnings: list[str] = []
    if is_overdue(record, today):
        warnings.append("outcome review is due")
    if record.status not in VALID_STATUSES:
        warnings.append(f"unsupported status: {record.status}")
    if record.direction not in VALID_DIRECTIONS:
        warnings.append(f"unsupported direction: {record.direction}")
    if record.language == "fa" and record.direction == "ltr":
        warnings.append("Persian records should not use ltr direction")
    if record.has_rtl_content() and record.direction == "ltr":
        warnings.append("RTL content detected in an ltr record")

    return ScoreResult(
        decision_id=record.id,
        title=record.title,
        score=score,
        passed=passed,
        missing=missing,
        warnings=warnings,
    )


def assumption_items(records: list[DecisionRecord]) -> list[AssumptionItem]:
    items: list[AssumptionItem] = []
    for record in records:
        for index, assumption in enumerate(record.assumptions):
            normalized = normalize_assumption(assumption)
            text = str(normalized.get("text", "")).strip()
            status = str(normalized.get("status", "")).strip() or "unvalidated"
            if text:
                items.append(
                    AssumptionItem(
                        decision_id=record.id,
                        title=record.title,
                        index=index,
                        text=text,
                        status=status,
                        owner=str(normalized.get("owner", "") or ""),
                        due_on=str(normalized.get("due_on", "") or ""),
                        signal=str(normalized.get("signal", "") or ""),
                        evidence_refs=list(normalized.get("evidence_refs", []) or []),
                        note=str(normalized.get("note", "") or ""),
                        reviewed_on=str(normalized.get("reviewed_on", "") or ""),
                    )
                )
    return items


def unvalidated_assumptions(records: list[DecisionRecord]) -> list[AssumptionItem]:
    unresolved = {"", "unknown", "unvalidated", "todo", "pending"}
    return [item for item in assumption_items(records) if item.status.lower() in unresolved]


def missing_metrics(records: list[DecisionRecord]) -> list[DecisionRecord]:
    return [record for record in records if not record.success_metrics]


def validate_record(
    record: DecisionRecord,
    today: date | None = None,
    records: list[DecisionRecord] | None = None,
) -> list[str]:
    issues: list[str] = []
    required = ["id", "title", "status", "date"]
    for key in required:
        if not is_present(record.metadata.get(key)):
            issues.append(f"{record.id or record.path.name}: missing {key}")

    if record.status not in VALID_STATUSES:
        issues.append(f"{record.id}: unsupported status '{record.status}'")
    if record.direction not in VALID_DIRECTIONS:
        issues.append(f"{record.id}: unsupported direction '{record.direction}'")
    if as_date(record.metadata.get("date")) is None:
        issues.append(f"{record.id}: date must be ISO formatted")
    if is_present(record.metadata.get("revisit_on")) and record.revisit_on is None:
        issues.append(f"{record.id}: revisit_on must be ISO formatted")
    if record.language == "fa" and record.direction == "ltr":
        issues.append(f"{record.id}: Persian records should use rtl or auto direction")
    if contains_rtl_text(record.metadata) and record.direction == "ltr":
        issues.append(f"{record.id}: RTL content should not be marked ltr")
    if is_overdue(record, today):
        issues.append(f"{record.id}: revisit date has passed and no outcome is recorded")
    issues.extend(relation_errors(record, records))
    return issues


def weekly_review(records: list[DecisionRecord], today: date | None = None) -> dict[str, Any]:
    current_date = today or date.today()
    due = [record for record in records if is_overdue(record, current_date)]
    metrics = missing_metrics(records)
    assumptions = unvalidated_assumptions(records)
    review_candidates = [
        record
        for record in records
        if record.revisit_on and record.revisit_on <= current_date and record.status != "reviewed"
    ]
    return {
        "due": due,
        "missing_metrics": metrics,
        "unvalidated_assumptions": assumptions,
        "review_candidates": review_candidates,
    }


def outcome_report(records: list[DecisionRecord], today: date | None = None) -> dict[str, Any]:
    current_date = today or date.today()
    assumptions = assumption_items(records)
    validated = [item for item in assumptions if item.status.lower() == "validated"]
    invalidated = [item for item in assumptions if item.status.lower() == "invalidated"]
    open_assumptions = unvalidated_assumptions(records)
    accepted_overdue = [
        record
        for record in records
        if record.status == "accepted" and is_overdue(record, current_date)
    ]
    invalidated_by_decision: dict[str, list[AssumptionItem]] = {}
    for item in invalidated:
        invalidated_by_decision.setdefault(item.decision_id, []).append(item)
    supersede_candidates = [
        record
        for record in records
        if record.status in {"accepted", "reviewed"}
        and (
            record.id in invalidated_by_decision
            or (record.status == "accepted" and is_overdue(record, current_date))
        )
    ]
    timeline = sorted(_decision_timeline(records), key=lambda item: (item["date"], item["id"], item["event"]))
    return {
        "accepted_overdue": accepted_overdue,
        "decisions_without_metrics": missing_metrics(records),
        "open_assumptions": open_assumptions,
        "validated_assumptions": validated,
        "invalidated_assumptions": invalidated,
        "supersede_candidates": supersede_candidates,
        "invalidated_by_decision": invalidated_by_decision,
        "timeline": timeline,
    }


def _decision_timeline(records: list[DecisionRecord]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for record in records:
        if record.decision_date:
            events.append(
                {
                    "date": record.decision_date.isoformat(),
                    "id": record.id,
                    "title": record.title,
                    "event": "decided",
                }
            )
        if record.revisit_on:
            events.append(
                {
                    "date": record.revisit_on.isoformat(),
                    "id": record.id,
                    "title": record.title,
                    "event": "revisit",
                }
            )
        if record.reviewed_on:
            events.append(
                {
                    "date": record.reviewed_on.isoformat(),
                    "id": record.id,
                    "title": record.title,
                    "event": "reviewed",
                }
            )
    return events
