from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"proposed", "accepted", "rejected", "superseded", "reviewed"}
VALID_DIRECTIONS = {"auto", "ltr", "rtl"}
VALID_RELATION_TYPES = {"related_to", "depends_on", "blocks", "supersedes", "informs"}


def as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def normalize_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [value]


def normalize_tag(value: Any) -> str:
    return str(value).strip()


def tag_key(value: Any) -> str:
    return normalize_tag(value).casefold()


def tag_labels(record: "DecisionRecord") -> list[str]:
    return [tag for tag in (normalize_tag(item) for item in record.tags) if tag]


def record_has_tag(record: "DecisionRecord", tag: str | None) -> bool:
    key = tag_key(tag or "")
    return bool(key) and any(tag_key(item) == key for item in record.tags)


def filter_records_by_tag(records: list["DecisionRecord"], tag: str | None) -> list["DecisionRecord"]:
    if not tag or not tag.strip():
        return records
    return [record for record in records if record_has_tag(record, tag)]


def collect_tags(records: list["DecisionRecord"]) -> list[str]:
    tags_by_key: dict[str, str] = {}
    for record in records:
        for tag in tag_labels(record):
            tags_by_key.setdefault(tag_key(tag), tag)
    return sorted(tags_by_key.values(), key=lambda value: value.casefold())


def contains_rtl_text(value: Any) -> bool:
    text = str(value)
    return any("\u0590" <= char <= "\u08ff" for char in text)


@dataclass
class DecisionRecord:
    path: Path
    metadata: dict[str, Any]
    body: str

    @property
    def id(self) -> str:
        return str(self.metadata.get("id", "")).strip()

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", "")).strip()

    @property
    def status(self) -> str:
        return str(self.metadata.get("status", "")).strip() or "proposed"

    @property
    def owner(self) -> str:
        return str(self.metadata.get("owner", "")).strip()

    @property
    def language(self) -> str:
        return str(self.metadata.get("language", "en")).strip() or "en"

    @property
    def direction(self) -> str:
        return str(self.metadata.get("direction", "auto")).strip() or "auto"

    @property
    def version(self) -> int:
        value = self.metadata.get("version", 1)
        try:
            version = int(value)
        except (TypeError, ValueError):
            return 1
        return max(version, 1)

    @property
    def created_at(self) -> str:
        return str(self.metadata.get("created_at", "") or "").strip()

    @property
    def updated_at(self) -> str:
        return str(self.metadata.get("updated_at", "") or "").strip()

    @property
    def decision_date(self) -> date | None:
        return as_date(self.metadata.get("date"))

    @property
    def revisit_on(self) -> date | None:
        return as_date(self.metadata.get("revisit_on"))

    @property
    def reviewed_on(self) -> date | None:
        return as_date(self.metadata.get("reviewed_on"))

    @property
    def outcome(self) -> Any:
        return self.metadata.get("outcome")

    @property
    def options(self) -> list[Any]:
        return normalize_list(self.metadata.get("options"))

    @property
    def rationale(self) -> list[Any]:
        return normalize_list(self.metadata.get("rationale"))

    @property
    def assumptions(self) -> list[Any]:
        return normalize_list(self.metadata.get("assumptions"))

    @property
    def success_metrics(self) -> list[Any]:
        return normalize_list(self.metadata.get("success_metrics"))

    @property
    def tags(self) -> list[Any]:
        return normalize_list(self.metadata.get("tags"))

    @property
    def parent_id(self) -> str:
        return str(self.metadata.get("parent_id", "") or "").strip()

    @property
    def related_decisions(self) -> list[Any]:
        return normalize_list(self.metadata.get("related_decisions"))

    def has_rtl_content(self) -> bool:
        return contains_rtl_text(self.metadata) or contains_rtl_text(self.body)
