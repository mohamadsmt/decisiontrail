from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from decisiontrail.config import DecisionTrailConfig
from decisiontrail.models import contains_rtl_text
from decisiontrail.parser import DraftDecision, parse_meeting_text
from decisiontrail.storage import create_decision


@dataclass(frozen=True)
class StoredDraft:
    id: str
    source: str
    title: str
    context: str
    options: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    raw_excerpt: str = ""


def drafts_path(root: Path) -> Path:
    return root / ".decisiontrail" / "drafts"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_draft_id(root: Path) -> str:
    year = date.today().year
    existing = []
    for path in drafts_path(root).glob(f"DRAFT-{year}-*.json"):
        try:
            existing.append(int(path.stem.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"DRAFT-{year}-{max(existing, default=0) + 1:03d}"


def normalize_draft(value: dict[str, Any]) -> StoredDraft:
    return StoredDraft(
        id=str(value.get("id", "") or "").strip(),
        source=str(value.get("source", "") or "manual").strip(),
        title=str(value.get("title", "") or "").strip(),
        context=str(value.get("context", "") or "").strip(),
        options=[str(item).strip() for item in value.get("options", []) if str(item).strip()],
        assumptions=[str(item).strip() for item in value.get("assumptions", []) if str(item).strip()],
        success_metrics=[str(item).strip() for item in value.get("success_metrics", []) if str(item).strip()],
        tags=[str(item).strip() for item in value.get("tags", []) if str(item).strip()],
        created_at=str(value.get("created_at", "") or "").strip(),
        raw_excerpt=str(value.get("raw_excerpt", "") or "").strip(),
    )


def draft_path(root: Path, draft_id: str) -> Path:
    return drafts_path(root) / f"{draft_id}.json"


def write_draft(root: Path, draft: StoredDraft) -> StoredDraft:
    if not draft.id:
        raise ValueError("Draft ID is required.")
    if not draft.title:
        raise ValueError("Draft title is required.")
    path = draft_path(root, draft.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(draft), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return draft


def create_draft(
    root: Path,
    *,
    source: str,
    title: str,
    context: str = "",
    options: list[str] | None = None,
    assumptions: list[str] | None = None,
    success_metrics: list[str] | None = None,
    tags: list[str] | None = None,
    raw_excerpt: str = "",
) -> StoredDraft:
    draft = StoredDraft(
        id=next_draft_id(root),
        source=source.strip() or "manual",
        title=title.strip(),
        context=context.strip(),
        options=options or [],
        assumptions=assumptions or [],
        success_metrics=success_metrics or [],
        tags=tags or [],
        created_at=_utc_timestamp(),
        raw_excerpt=raw_excerpt.strip(),
    )
    return write_draft(root, draft)


def create_draft_from_parsed(root: Path, draft: DraftDecision, *, source: str, raw_excerpt: str = "") -> StoredDraft:
    return create_draft(
        root,
        source=source,
        title=draft.title,
        context=draft.context,
        options=draft.options,
        assumptions=draft.assumptions,
        success_metrics=draft.success_metrics,
        raw_excerpt=raw_excerpt or draft.context,
    )


def create_drafts_from_meeting(root: Path, meeting_text: str, *, source_name: str = "meeting notes") -> list[StoredDraft]:
    return [
        create_draft_from_parsed(root, draft, source=source_name, raw_excerpt=meeting_text)
        for draft in parse_meeting_text(meeting_text, source_name=source_name)
    ]


def list_drafts(root: Path) -> list[StoredDraft]:
    directory = drafts_path(root)
    if not directory.exists():
        return []
    drafts = []
    for path in sorted(directory.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            drafts.append(normalize_draft(loaded))
    return drafts


def load_draft(root: Path, draft_id: str) -> StoredDraft:
    key = draft_id.strip().casefold()
    for draft in list_drafts(root):
        if draft.id.casefold() == key:
            return draft
    raise FileNotFoundError(f"No draft found for '{draft_id}'.")


def delete_draft(root: Path, draft_id: str) -> StoredDraft:
    draft = load_draft(root, draft_id)
    path = draft_path(root, draft.id)
    if path.exists():
        path.unlink()
    return draft


def promote_draft(
    root: Path,
    config: DecisionTrailConfig,
    draft_id: str,
    *,
    owner: str = "",
    status: str = "proposed",
    delete_after: bool = True,
) -> Any:
    draft = load_draft(root, draft_id)
    has_rtl = contains_rtl_text(draft.title) or contains_rtl_text(draft.context)
    record = create_decision(
        root,
        config,
        draft.title,
        owner=owner.strip(),
        status=status,
        context=draft.context,
        options=draft.options,
        assumptions=draft.assumptions,
        success_metrics=draft.success_metrics,
        tags=draft.tags,
        language="fa" if has_rtl else "en",
        direction="rtl" if has_rtl else "auto",
        source="draft",
    )
    if delete_after:
        delete_draft(root, draft.id)
    return record
