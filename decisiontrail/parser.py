from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


DECISION_HEADING = re.compile(r"^\s*#{1,6}\s*(?:Decision|Decision candidate|تصمیم)\s*[:：-]?\s*(.+)$", re.IGNORECASE)
DECISION_BULLET = re.compile(r"^\s*[-*]\s*(?:Decision|Decided|تصمیم)\s*[:：-]\s*(.+)$", re.IGNORECASE)
ASSUMPTION_LINE = re.compile(r"^\s*[-*]?\s*(?:Assumption|فرض)\s*[:：-]\s*(.+)$", re.IGNORECASE)
METRIC_LINE = re.compile(r"^\s*[-*]?\s*(?:Metric|Success metric|معیار)\s*[:：-]\s*(.+)$", re.IGNORECASE)
OPTION_LINE = re.compile(r"^\s*[-*]?\s*(?:Option|گزینه)\s*[:：-]\s*(.+)$", re.IGNORECASE)


@dataclass
class DraftDecision:
    title: str
    context: str
    options: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)


def parse_meeting_notes(path: Path) -> list[DraftDecision]:
    return parse_meeting_text(path.read_text(encoding="utf-8"), source_name=path.name)


def parse_meeting_text(text: str, source_name: str = "meeting notes") -> list[DraftDecision]:
    lines = text.splitlines()
    drafts: list[DraftDecision] = []
    current: DraftDecision | None = None
    context_buffer: list[str] = []

    for line in lines:
        heading = DECISION_HEADING.match(line)
        bullet = DECISION_BULLET.match(line)
        match = heading or bullet
        if match:
            if current:
                current.context = _clean_context(current.context, context_buffer)
                drafts.append(current)
            title = match.group(1).strip()
            current = DraftDecision(title=title, context=f"Extracted from {source_name}.")
            context_buffer = []
            continue

        if current is None:
            continue

        assumption = ASSUMPTION_LINE.match(line)
        metric = METRIC_LINE.match(line)
        option = OPTION_LINE.match(line)
        if assumption:
            current.assumptions.append(assumption.group(1).strip())
        elif metric:
            current.success_metrics.append(metric.group(1).strip())
        elif option:
            current.options.append(option.group(1).strip())
        elif line.strip():
            context_buffer.append(line.strip())

    if current:
        current.context = _clean_context(current.context, context_buffer)
        drafts.append(current)

    return drafts


def _clean_context(default: str, lines: list[str]) -> str:
    if not lines:
        return default
    return " ".join(lines).strip()
