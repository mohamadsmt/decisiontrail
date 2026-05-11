from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from decisiontrail.config import DecisionTrailConfig
from decisiontrail.models import DecisionRecord, VALID_DIRECTIONS, VALID_STATUSES
from decisiontrail.templates import DEFAULT_DECISION_BODY_TEMPLATE, render_decision_body


ID_PATTERN = re.compile(r"^DEC-(?P<year>\d{4})-(?P<number>\d{3,})$")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            raw_yaml = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            loaded = yaml.safe_load(raw_yaml) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Decision frontmatter must be a YAML mapping.")
            return loaded, body
    raise ValueError("Decision frontmatter is missing a closing '---'.")


def render_frontmatter(metadata: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return f"---\n{yaml_text}---\n{body.lstrip()}"


def read_decision(path: Path) -> DecisionRecord:
    metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return DecisionRecord(path=path, metadata=metadata, body=body)


def write_decision(record: DecisionRecord) -> None:
    record.path.write_text(render_frontmatter(record.metadata, record.body), encoding="utf-8")


def decisions_path(root: Path, config: DecisionTrailConfig) -> Path:
    return root / config.decisions_dir


def load_decisions(root: Path, config: DecisionTrailConfig) -> list[DecisionRecord]:
    directory = decisions_path(root, config)
    if not directory.exists():
        return []
    records = [read_decision(path) for path in sorted(directory.glob("*.md"))]
    return sorted(records, key=lambda record: (record.id, record.path.name))


def load_decision(root: Path, config: DecisionTrailConfig, identifier: str) -> DecisionRecord:
    candidate = Path(identifier)
    if candidate.exists():
        return read_decision(candidate)

    normalized = identifier.strip().lower()
    for record in load_decisions(root, config):
        if record.id.lower() == normalized or record.path.stem.lower() == normalized:
            return record
    raise FileNotFoundError(f"No decision found for '{identifier}'.")


def slugify(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "decision"


def next_decision_id(root: Path, config: DecisionTrailConfig, year: int | None = None) -> str:
    target_year = year or date.today().year
    highest = 0
    for record in load_decisions(root, config):
        match = ID_PATTERN.match(record.id)
        if match and int(match.group("year")) == target_year:
            highest = max(highest, int(match.group("number")))
    return f"DEC-{target_year}-{highest + 1:03d}"


def build_metadata(
    *,
    decision_id: str,
    title: str,
    status: str = "proposed",
    owner: str = "",
    created_on: date | None = None,
    context: str = "",
    options: list[Any] | None = None,
    decision: str = "",
    rationale: list[Any] | None = None,
    assumptions: list[Any] | None = None,
    success_metrics: list[Any] | None = None,
    revisit_on: str = "",
    language: str = "en",
    direction: str = "auto",
    tags: list[str] | None = None,
    parent_id: str = "",
    related_decisions: list[Any] | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"Unsupported direction: {direction}")

    return {
        "id": decision_id,
        "title": title,
        "status": status,
        "date": created_on or date.today(),
        "owner": owner,
        "context": context,
        "options": options or [],
        "decision": decision,
        "rationale": rationale or [],
        "assumptions": assumptions or [],
        "success_metrics": success_metrics or [],
        "revisit_on": revisit_on,
        "outcome": "",
        "reviewed_on": "",
        "experiment_links": [],
        "tags": tags or [],
        "parent_id": parent_id,
        "related_decisions": related_decisions or [],
        "language": language,
        "direction": direction,
    }


def create_decision(
    root: Path,
    config: DecisionTrailConfig,
    title: str,
    *,
    status: str = "proposed",
    owner: str = "",
    created_on: date | None = None,
    context: str = "",
    options: list[Any] | None = None,
    decision: str = "",
    rationale: list[Any] | None = None,
    assumptions: list[Any] | None = None,
    success_metrics: list[Any] | None = None,
    revisit_on: str = "",
    language: str = "en",
    direction: str = "auto",
    tags: list[str] | None = None,
    parent_id: str = "",
    related_decisions: list[Any] | None = None,
) -> DecisionRecord:
    directory = decisions_path(root, config)
    directory.mkdir(parents=True, exist_ok=True)

    decision_id = next_decision_id(root, config, (created_on or date.today()).year)
    metadata = build_metadata(
        decision_id=decision_id,
        title=title,
        status=status,
        owner=owner,
        created_on=created_on,
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
    body = render_decision_body(root, config.templates_dir, metadata)
    path = directory / f"{decision_id}-{slugify(title)}.md"
    record = DecisionRecord(path=path, metadata=metadata, body=body)
    write_decision(record)
    return record


def ensure_template(root: Path, config: DecisionTrailConfig, overwrite: bool = False) -> Path:
    template_dir = root / config.templates_dir
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / "decision.md.j2"
    if not template_path.exists() or overwrite:
        template_path.write_text(DEFAULT_DECISION_BODY_TEMPLATE, encoding="utf-8")
    return template_path
