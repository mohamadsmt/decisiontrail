from __future__ import annotations

import copy
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from decisiontrail.config import DecisionTrailConfig
from decisiontrail.models import DecisionRecord, VALID_DECISION_TYPES, VALID_DIRECTIONS, VALID_STATUSES
from decisiontrail.templates import DEFAULT_DECISION_BODY_TEMPLATE, render_decision_body


ID_PATTERN = re.compile(r"^DEC-(?P<year>\d{4})-(?P<number>\d{3,})$")
VERSION_METADATA_FIELDS = {"version", "created_at", "updated_at"}


@dataclass(frozen=True)
class VersionWriteResult:
    changed: bool
    version: int
    event: dict[str, Any] | None = None


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


def copy_decision_record(record: DecisionRecord) -> DecisionRecord:
    return DecisionRecord(path=record.path, metadata=copy.deepcopy(record.metadata), body=record.body)


def history_path(root: Path, config: DecisionTrailConfig) -> Path:
    return root / config.history_dir


def decision_history_path(root: Path, config: DecisionTrailConfig, decision_id: str) -> Path:
    return history_path(root, config) / decision_id


def version_snapshot_path(root: Path, config: DecisionTrailConfig, decision_id: str, version: int) -> Path:
    return decision_history_path(root, config, decision_id) / f"v{version:04d}.md"


def history_events_path(root: Path, config: DecisionTrailConfig, decision_id: str) -> Path:
    return decision_history_path(root, config, decision_id) / "events.jsonl"


def metadata_version(metadata: dict[str, Any]) -> int:
    try:
        version = int(metadata.get("version", 1))
    except (TypeError, ValueError):
        return 1
    return max(version, 1)


def read_history_events(root: Path, config: DecisionTrailConfig, decision_id: str) -> list[dict[str, Any]]:
    path = history_events_path(root, config, decision_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


def load_history_snapshot(root: Path, config: DecisionTrailConfig, decision_id: str, version: int) -> DecisionRecord:
    path = version_snapshot_path(root, config, decision_id, version)
    if not path.exists():
        raise FileNotFoundError(f"No history snapshot found for {decision_id} v{version}.")
    return read_decision(path)


def record_text_for_diff(record: DecisionRecord) -> str:
    return render_frontmatter(record.metadata, record.body)


def diff_decision_records(from_record: DecisionRecord, to_record: DecisionRecord) -> str:
    from_name = f"{from_record.id or from_record.path.stem}@v{metadata_version(from_record.metadata)}"
    to_name = f"{to_record.id or to_record.path.stem}@v{metadata_version(to_record.metadata)}"
    return "".join(
        difflib.unified_diff(
            record_text_for_diff(from_record).splitlines(keepends=True),
            record_text_for_diff(to_record).splitlines(keepends=True),
            fromfile=from_name,
            tofile=to_name,
        )
    )


def restore_history_snapshot(
    root: Path,
    config: DecisionTrailConfig,
    record: DecisionRecord,
    *,
    version: int,
    source: str,
) -> VersionWriteResult:
    snapshot = load_history_snapshot(root, config, record.id, version)
    restored = copy_decision_record(snapshot)
    restored.path = record.path
    restored.metadata["id"] = record.id
    return write_versioned_decision(root, config, copy_decision_record(record), restored, source=source, action="restored")


def write_versioned_decision(
    root: Path,
    config: DecisionTrailConfig,
    previous: DecisionRecord,
    record: DecisionRecord,
    *,
    source: str,
    action: str,
) -> VersionWriteResult:
    if not _record_content_changed(previous, record):
        return VersionWriteResult(changed=False, version=metadata_version(previous.metadata))

    changed_at = _utc_timestamp()
    previous_version = metadata_version(previous.metadata)
    created_at = _created_timestamp(previous, changed_at)
    _ensure_snapshot(
        root,
        config,
        previous,
        version=previous_version,
        created_at=created_at,
        updated_at=previous.updated_at or created_at,
        source=source,
        action="baseline",
        previous_version=(previous_version - 1) if previous_version > 1 else None,
        changed_at=changed_at,
        changed_fields=[],
    )

    next_version = previous_version + 1
    _apply_version_metadata(record.metadata, version=next_version, created_at=created_at, updated_at=changed_at)
    write_decision(record)
    snapshot = _write_snapshot(root, config, record)
    event = _append_history_event(
        root,
        config,
        record.id,
        version=next_version,
        previous_version=previous_version,
        changed_at=changed_at,
        source=source,
        action=action,
        changed_fields=_changed_fields(previous, record),
        snapshot=snapshot,
    )
    return VersionWriteResult(changed=True, version=next_version, event=event)


def delete_versioned_decision(
    root: Path,
    config: DecisionTrailConfig,
    record: DecisionRecord,
    *,
    source: str,
    action: str = "deleted",
) -> VersionWriteResult:
    changed_at = _utc_timestamp()
    previous_version = metadata_version(record.metadata)
    created_at = _created_timestamp(record, changed_at)
    _ensure_snapshot(
        root,
        config,
        record,
        version=previous_version,
        created_at=created_at,
        updated_at=record.updated_at or created_at,
        source=source,
        action="baseline",
        previous_version=(previous_version - 1) if previous_version > 1 else None,
        changed_at=changed_at,
        changed_fields=[],
    )

    final_record = copy_decision_record(record)
    final_version = previous_version + 1
    _apply_version_metadata(final_record.metadata, version=final_version, created_at=created_at, updated_at=changed_at)
    snapshot = _write_snapshot(root, config, final_record)
    event = _append_history_event(
        root,
        config,
        record.id,
        version=final_version,
        previous_version=previous_version,
        changed_at=changed_at,
        source=source,
        action=action,
        changed_fields=["deleted"],
        snapshot=snapshot,
    )
    record.path.unlink()
    return VersionWriteResult(changed=True, version=final_version, event=event)


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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _created_timestamp(record: DecisionRecord, fallback: str) -> str:
    if record.created_at:
        return record.created_at
    if record.decision_date:
        return f"{record.decision_date.isoformat()}T00:00:00Z"
    return fallback


def _apply_version_metadata(metadata: dict[str, Any], *, version: int, created_at: str, updated_at: str) -> None:
    metadata["version"] = version
    metadata["created_at"] = created_at
    metadata["updated_at"] = updated_at


def _metadata_for_content_compare(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in VERSION_METADATA_FIELDS}


def _record_content_changed(previous: DecisionRecord, record: DecisionRecord) -> bool:
    return (
        _metadata_for_content_compare(previous.metadata) != _metadata_for_content_compare(record.metadata)
        or previous.body != record.body
    )


def _changed_fields(previous: DecisionRecord, record: DecisionRecord) -> list[str]:
    fields = [
        key
        for key in sorted(set(previous.metadata) | set(record.metadata))
        if key not in VERSION_METADATA_FIELDS and previous.metadata.get(key) != record.metadata.get(key)
    ]
    if previous.body != record.body:
        fields.append("body")
    return fields


def _record_with_version(record: DecisionRecord, *, version: int, created_at: str, updated_at: str) -> DecisionRecord:
    snapshot_record = copy_decision_record(record)
    _apply_version_metadata(snapshot_record.metadata, version=version, created_at=created_at, updated_at=updated_at)
    return snapshot_record


def _write_snapshot(root: Path, config: DecisionTrailConfig, record: DecisionRecord) -> Path:
    version = metadata_version(record.metadata)
    path = version_snapshot_path(root, config, record.id, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_frontmatter(record.metadata, record.body), encoding="utf-8")
    return path


def _append_history_event(
    root: Path,
    config: DecisionTrailConfig,
    decision_id: str,
    *,
    version: int,
    previous_version: int | None,
    changed_at: str,
    source: str,
    action: str,
    changed_fields: list[str],
    snapshot: Path,
) -> dict[str, Any]:
    event = {
        "version": version,
        "previous_version": previous_version,
        "changed_at": changed_at,
        "source": source,
        "action": action,
        "changed_fields": changed_fields,
        "snapshot": _relative_path(root, snapshot),
    }
    path = history_events_path(root, config, decision_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_jsonable(event), ensure_ascii=False) + "\n")
    return event


def _ensure_snapshot(
    root: Path,
    config: DecisionTrailConfig,
    record: DecisionRecord,
    *,
    version: int,
    created_at: str,
    updated_at: str,
    source: str,
    action: str,
    previous_version: int | None,
    changed_at: str,
    changed_fields: list[str],
) -> None:
    path = version_snapshot_path(root, config, record.id, version)
    if path.exists():
        return
    snapshot_record = _record_with_version(record, version=version, created_at=created_at, updated_at=updated_at)
    snapshot = _write_snapshot(root, config, snapshot_record)
    _append_history_event(
        root,
        config,
        record.id,
        version=version,
        previous_version=previous_version,
        changed_at=changed_at,
        source=source,
        action=action,
        changed_fields=changed_fields,
        snapshot=snapshot,
    )


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
    decision_type: str = "general",
    evidence: list[Any] | None = None,
    metric_updates: list[Any] | None = None,
    parent_id: str = "",
    related_decisions: list[Any] | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"Unsupported direction: {direction}")
    if decision_type not in VALID_DECISION_TYPES:
        raise ValueError(f"Unsupported decision_type: {decision_type}")

    return {
        "id": decision_id,
        "title": title,
        "decision_type": decision_type,
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
        "evidence": evidence or [],
        "metric_updates": metric_updates or [],
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
    decision_type: str = "general",
    evidence: list[Any] | None = None,
    metric_updates: list[Any] | None = None,
    parent_id: str = "",
    related_decisions: list[Any] | None = None,
    source: str = "storage",
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
        decision_type=decision_type,
        evidence=evidence,
        metric_updates=metric_updates,
        parent_id=parent_id,
        related_decisions=related_decisions,
    )
    timestamp = _utc_timestamp()
    _apply_version_metadata(metadata, version=1, created_at=timestamp, updated_at=timestamp)
    body = render_decision_body(root, config.templates_dir, metadata)
    path = directory / f"{decision_id}-{slugify(title)}.md"
    record = DecisionRecord(path=path, metadata=metadata, body=body)
    write_decision(record)
    snapshot = _write_snapshot(root, config, record)
    _append_history_event(
        root,
        config,
        record.id,
        version=1,
        previous_version=None,
        changed_at=timestamp,
        source=source,
        action="created",
        changed_fields=["created"],
        snapshot=snapshot,
    )
    return record


def ensure_template(root: Path, config: DecisionTrailConfig, overwrite: bool = False) -> Path:
    template_dir = root / config.templates_dir
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / "decision.md.j2"
    if not template_path.exists() or overwrite:
        template_path.write_text(DEFAULT_DECISION_BODY_TEMPLATE, encoding="utf-8")
    return template_path
