from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"proposed", "accepted", "rejected", "superseded", "reviewed"}
VALID_DIRECTIONS = {"auto", "ltr", "rtl"}


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

    def has_rtl_content(self) -> bool:
        return contains_rtl_text(self.metadata) or contains_rtl_text(self.body)
