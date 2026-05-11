from __future__ import annotations

from datetime import date

from decisiontrail.config import load_config
from decisiontrail.review import (
    is_overdue,
    score_decision,
    unvalidated_assumptions,
    validate_record,
    weekly_review,
)
from decisiontrail.storage import create_decision


def test_scorecard_rewards_complete_decision(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Complete decision",
        owner="Product",
        context="We need margin control.",
        options=["Keep pricing", "Launch tiers"],
        decision="Launch tiers",
        rationale=["Lower churn risk"],
        assumptions=[{"text": "Merchants accept tiers.", "status": "validated"}],
        success_metrics=["gross_margin"],
        revisit_on="2026-07-15",
    )

    result = score_decision(record, today=date(2026, 5, 11))

    assert result.score == 100
    assert result.missing == []


def test_overdue_detection_requires_missing_outcome(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(tmp_path, config, "Old decision", revisit_on="2026-01-01")

    assert is_overdue(record, today=date(2026, 5, 11))

    record.metadata["outcome"] = "Worked."

    assert not is_overdue(record, today=date(2026, 5, 11))


def test_weekly_review_finds_missing_metrics_and_assumptions(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Risk decision",
        assumptions=["Customers will accept the delay."],
        revisit_on="2026-01-01",
    )

    report = weekly_review([record], today=date(2026, 5, 11))

    assert report["due"] == [record]
    assert report["missing_metrics"] == [record]
    assert len(report["unvalidated_assumptions"]) == 1


def test_validate_record_flags_ltr_persian_metadata(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "تصمیم فارسی",
        language="fa",
        direction="ltr",
    )

    issues = validate_record(record)

    assert any("Persian records" in issue for issue in issues)


def test_unvalidated_assumptions_accepts_structured_status(tmp_path) -> None:
    config = load_config(tmp_path)
    record = create_decision(
        tmp_path,
        config,
        "Assumption decision",
        assumptions=[
            {"text": "Validated assumption", "status": "validated"},
            {"text": "Pending assumption", "status": "pending"},
        ],
    )

    unresolved = unvalidated_assumptions([record])

    assert [item.text for item in unresolved] == ["Pending assumption"]
