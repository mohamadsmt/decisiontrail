from __future__ import annotations

from decisiontrail.web.forms import DecisionFormData, form_to_create_kwargs, parse_assumptions, split_lines, validate_decision_form


def test_split_lines_ignores_blank_lines_and_trims_values() -> None:
    assert split_lines(" one \n\n two\n ") == ["one", "two"]


def test_parse_assumptions_preserves_persian_text() -> None:
    assumptions = parse_assumptions("فروشنده‌ها reliability را ترجیح می‌دهند.\nRetention stays stable.")

    assert assumptions == [
        {"text": "فروشنده‌ها reliability را ترجیح می‌دهند.", "status": "unvalidated"},
        {"text": "Retention stays stable.", "status": "unvalidated"},
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
    )

    kwargs = form_to_create_kwargs(data)

    assert kwargs["owner"] == "Product"
    assert kwargs["options"] == ["Keep", "Launch tiers"]
    assert kwargs["assumptions"] == [{"text": "Merchants accept tiers", "status": "unvalidated"}]
    assert kwargs["success_metrics"] == ["gross_margin", "retention"]
    assert kwargs["tags"] == ["pricing", "growth"]
    assert kwargs["language"] == "fa"
    assert kwargs["direction"] == "rtl"


def test_validate_decision_form_rejects_invalid_status_direction_and_date() -> None:
    errors = validate_decision_form(
        DecisionFormData(title="", status="done", direction="sideways", revisit_on="11-05-2026")
    )

    assert "Title is required." in errors
    assert any("Status must be one of" in error for error in errors)
    assert "Direction must be auto, ltr, or rtl." in errors
    assert "Revisit date must use ISO format: YYYY-MM-DD." in errors
