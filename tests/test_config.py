from __future__ import annotations

from pathlib import Path

from decisiontrail.config import load_config


def test_local_config_overrides_project_config(tmp_path: Path) -> None:
    (tmp_path / "decisiontrail.yml").write_text(
        "decisions_dir: decisions\n"
        "templates_dir: templates\n"
        "score_threshold: 80\n",
        encoding="utf-8",
    )
    (tmp_path / "decisiontrail.local.yml").write_text(
        "decisions_dir: decisions.local\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.decisions_dir == "decisions.local"
    assert config.templates_dir == "templates"
    assert config.history_dir == ".decisiontrail/history"
    assert config.score_threshold == 80
