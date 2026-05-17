from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BUILT_IN_VIEWS: dict[str, dict[str, Any]] = {
    "Due": {"name": "Due", "q": "", "status": "", "owner": "", "tag": "", "due": True, "builtin": True},
    "Risk": {"name": "Risk", "q": "risk", "status": "", "owner": "", "tag": "", "due": False, "builtin": True},
    "AI": {"name": "AI", "q": "ai", "status": "", "owner": "", "tag": "", "due": False, "builtin": True},
    "Pricing": {"name": "Pricing", "q": "pricing", "status": "", "owner": "", "tag": "", "due": False, "builtin": True},
    "Hiring": {"name": "Hiring", "q": "hiring", "status": "", "owner": "", "tag": "", "due": False, "builtin": True},
}


def views_path(root: Path) -> Path:
    return root / ".decisiontrail" / "views.json"


def normalize_view(value: dict[str, Any]) -> dict[str, Any]:
    name = str(value.get("name", "") or "").strip()
    if not name:
        raise ValueError("View name is required.")
    return {
        "name": name,
        "q": str(value.get("q", "") or "").strip(),
        "status": str(value.get("status", "") or "").strip(),
        "owner": str(value.get("owner", "") or "").strip(),
        "tag": str(value.get("tag", "") or "").strip(),
        "due": bool(value.get("due", False)),
        "builtin": bool(value.get("builtin", False)),
    }


def load_user_views(root: Path) -> list[dict[str, Any]]:
    path = views_path(root)
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8") or "[]")
    if not isinstance(loaded, list):
        raise ValueError("views.json must contain a JSON list.")
    return [normalize_view(item) for item in loaded if isinstance(item, dict)]


def write_user_views(root: Path, views: list[dict[str, Any]]) -> None:
    path = views_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([normalize_view(view) for view in views], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_views(root: Path) -> list[dict[str, Any]]:
    user_views = load_user_views(root)
    return [*BUILT_IN_VIEWS.values(), *user_views]


def save_user_view(
    root: Path,
    *,
    name: str,
    q: str = "",
    status: str = "",
    owner: str = "",
    tag: str = "",
    due: bool = False,
) -> dict[str, Any]:
    view = normalize_view({"name": name, "q": q, "status": status, "owner": owner, "tag": tag, "due": due})
    views = [item for item in load_user_views(root) if item["name"].casefold() != view["name"].casefold()]
    views.append(view)
    views.sort(key=lambda item: item["name"].casefold())
    write_user_views(root, views)
    return view


def delete_user_view(root: Path, name: str) -> bool:
    key = name.strip().casefold()
    views = load_user_views(root)
    kept = [view for view in views if view["name"].casefold() != key]
    if len(kept) == len(views):
        return False
    write_user_views(root, kept)
    return True


def resolve_view(root: Path, name: str) -> dict[str, Any] | None:
    if not name.strip():
        return None
    key = name.strip().casefold()
    for view in list_views(root):
        if view["name"].casefold() == key:
            return view
    return None
