from __future__ import annotations

from decisiontrail.config import load_config
from decisiontrail.storage import create_decision
from decisiontrail.web.forms import (
    DecisionFormData,
    form_to_create_kwargs,
    parse_assumptions,
    record_to_form_data,
    split_lines,
    validate_decision_form,
)


def test_split_lines_ignores_blank_lines_and_trims_values() -> None:
    assert split_lines(" one \n\n two\n ") == ["one", "two"]


def test_parse_assumptions_preserves_persian_text() -> None:
    assumptions = parse_assumptions("فروشنده‌ها reliability را ترجیح می‌دهند.\nRetention stays stable.")

    assert assumptions == [
        {"text": "فروشنده‌ها reliability را ترجیح می‌دهند.", "status": "unvalidated"},
        {"text": "Retention stays stable.", "status": "unvalidated"},
    ]


def test_parse_assumptions_supports_status_and_note() -> None:
    assumptions = parse_assumptions("validated: کاربران مسیر کوتاه‌تر را ترجیح می‌دهند. | Checked in cohort A")

    assert assumptions == [
        {
            "text": "کاربران مسیر کوتاه‌تر را ترجیح می‌دهند.",
            "status": "validated",
            "note": "Checked in cohort A",
        }
    ]


def test_form_to_create_kwargs_maps_multiline_fields() -> None:
    data = DecisionFormData(
        title="Launch pricing",
        owner=" Product ",
        context="Context",
        options="Keep\nLaunch tiers",
        rationale="Margin\nRetention",
        assumptions="Merchants accept tiers",
        success_metrics="gross_margin\nretention",
        tags="pricing\ngrowth",
        language="fa",
        direction="rtl",
        parent_id="DEC-2026-001",
        related_decisions="depends_on: DEC-2026-002 | Required first",
    )

    kwargs = form_to_create_kwargs(data)

    assert kwargs["owner"] == "Product"
    assert kwargs["options"] == ["Keep", "Launch tiers"]
    assert kwargs["assumptions"] == [{"text": "Merchants accept tiers", "status": "unvalidated"}]
    assert kwargs["success_metrics"] == ["gross_margin", "retention"]
    assert kwargs["tags"] == ["pricing", "growth"]
    assert kwargs["language"] == "fa"
    assert kwargs["direction"] == "rtl"
    assert kwargs["parent_id"] == "DEC-2026-001"
    assert kwargs["related_decisions"] == [{"id": "DEC-2026-002", "type": "depends_on", "note": "Required first"}]


def test_validate_decision_form_rejects_invalid_status_direction_and_date() -> None:
    errors = validate_decision_form(
        DecisionFormData(title="", status="done", direction="sideways", revisit_on="11-05-2026")
    )

    assert "Title is required." in errors
    assert any("Status must be one of" in error for error in errors)
    assert "Direction must be auto, ltr, or rtl." in errors
    assert "Revisit date must use ISO format: YYYY-MM-DD." in errors


def test_validate_decision_form_rejects_unknown_relationship_fields() -> None:
    errors = validate_decision_form(
        DecisionFormData(
            title="Bad relation",
            parent_id="DEC-2026-404",
            related_decisions="bad_type: DEC-2026-999",
        ),
        known_ids={"DEC-2026-001"},
    )

    assert "Parent decision does not exist: DEC-2026-404." in errors
    assert "Unsupported relation type: bad_type." in errors
    assert "Related decision does not exist: DEC-2026-999." in errors


def test_record_to_form_data_maps_editable_fields_and_body(tmp_path) -> None:
    config = load_config(tmp_path)
    target = create_decision(tmp_path, config, "Target")
    record = create_decision(
        tmp_path,
        config,
        "Editable",
        assumptions=[{"text": "Persian فرض", "status": "validated", "note": "Checked"}],
        related_decisions=[{"id": target.id, "type": "informs", "note": "Context"}],
    )
    record.body = "# Custom body\n\nManual notes."

    data = record_to_form_data(record)

    assert data.title == "Editable"
    assert data.assumptions == "validated: Persian فرض | Checked"
    assert data.related_decisions == f"informs: {target.id} | Context"
    assert data.body == "# Custom body\n\nManual notes."
