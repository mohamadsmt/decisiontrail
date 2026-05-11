from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from decisiontrail.models import VALID_DIRECTIONS, VALID_STATUSES


@dataclass(frozen=True)
class DecisionFormData:
    title: str = ""
    owner: str = ""
    status: str = "proposed"
    context: str = ""
    options: str = ""
    decision: str = ""
    rationale: str = ""
    assumptions: str = ""
    success_metrics: str = ""
    revisit_on: str = ""
    language: str = "en"
    direction: str = "auto"
    tags: str = ""


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def parse_assumptions(value: str) -> list[dict[str, str]]:
    return [{"text": line, "status": "unvalidated"} for line in split_lines(value)]


def validate_decision_form(data: DecisionFormData) -> list[str]:
    errors: list[str] = []
    if not data.title.strip():
        errors.append("Title is required.")
    if data.status not in VALID_STATUSES:
        errors.append(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}.")
    if data.direction not in VALID_DIRECTIONS:
        errors.append("Direction must be auto, ltr, or rtl.")
    if data.revisit_on.strip():
        try:
            date.fromisoformat(data.revisit_on.strip())
        except ValueError:
            errors.append("Revisit date must use ISO format: YYYY-MM-DD.")
    return errors


def form_to_create_kwargs(data: DecisionFormData) -> dict[str, Any]:
    return {
        "status": data.status,
        "owner": data.owner.strip(),
        "context": data.context.strip(),
        "options": split_lines(data.options),
        "decision": data.decision.strip(),
        "rationale": split_lines(data.rationale),
        "assumptions": parse_assumptions(data.assumptions),
        "success_metrics": split_lines(data.success_metrics),
        "revisit_on": data.revisit_on.strip(),
        "language": data.language.strip() or "en",
        "direction": data.direction,
        "tags": split_lines(data.tags),
    }
