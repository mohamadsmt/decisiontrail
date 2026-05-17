from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONFIG_FILE = "decisiontrail.yml"
LOCAL_CONFIG_FILE = "decisiontrail.local.yml"


@dataclass(frozen=True)
class DecisionTrailConfig:
    decisions_dir: str = "decisions"
    templates_dir: str = "templates"
    export_dir: str = "site"
    history_dir: str = ".decisiontrail/history"
    score_threshold: int = 70
    warn_only: bool = True
    overdue_policy: str = "warn"
    missing_metric_policy: str = "warn"
    unvalidated_assumption_policy: str = "warn"


DEFAULT_CONFIG: dict[str, Any] = {
    "decisions_dir": "decisions",
    "templates_dir": "templates",
    "export_dir": "site",
    "history_dir": ".decisiontrail/history",
    "score_threshold": 70,
    "warn_only": True,
    "overdue_policy": "warn",
    "missing_metric_policy": "warn",
    "unvalidated_assumption_policy": "warn",
}


def _load_config_file(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping.")
    return loaded


def load_config(root: Path) -> DecisionTrailConfig:
    data: dict[str, Any] = {}
    config_path = root / CONFIG_FILE
    if config_path.exists():
        data = _load_config_file(config_path)

    local_config_path = root / LOCAL_CONFIG_FILE
    if local_config_path.exists():
        data = {**data, **_load_config_file(local_config_path)}

    merged = {**DEFAULT_CONFIG, **data}
    return DecisionTrailConfig(
        decisions_dir=str(merged["decisions_dir"]),
        templates_dir=str(merged["templates_dir"]),
        export_dir=str(merged["export_dir"]),
        history_dir=str(merged["history_dir"]),
        score_threshold=int(merged["score_threshold"]),
        warn_only=bool(merged["warn_only"]),
        overdue_policy=str(merged["overdue_policy"]),
        missing_metric_policy=str(merged["missing_metric_policy"]),
        unvalidated_assumption_policy=str(merged["unvalidated_assumption_policy"]),
    )


def dump_default_config(root: Path, overwrite: bool = False) -> Path:
    config_path = root / CONFIG_FILE
    if config_path.exists() and not overwrite:
        return config_path

    config_path.write_text(
        yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return config_path
