from __future__ import annotations

from pathlib import Path

from jinja2 import Template
from markdown import markdown

from decisiontrail.config import DecisionTrailConfig
from decisiontrail.models import DecisionRecord
from decisiontrail.storage import slugify
from decisiontrail.templates import HTML_CSS, HTML_DECISION_TEMPLATE, HTML_INDEX_TEMPLATE


def html_direction(record: DecisionRecord) -> str:
    return record.direction if record.direction in {"ltr", "rtl", "auto"} else "auto"


def decision_href(record: DecisionRecord) -> str:
    stem = f"{record.id}-{slugify(record.title)}" if record.id else slugify(record.title)
    return f"{stem}.html"


def export_html(records: list[DecisionRecord], output_dir: Path, config: DecisionTrailConfig) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_template = Template(HTML_INDEX_TEMPLATE)
    decision_template = Template(HTML_DECISION_TEMPLATE)

    pages: list[Path] = []
    index_items = []
    for record in records:
        href = decision_href(record)
        index_items.append({"record": record, "href": href})
        body_html = markdown(record.body, extensions=["fenced_code", "tables"])
        details = [
            ("Owner", record.owner or "Unassigned"),
            ("Date", record.decision_date or "Unknown"),
            ("Revisit", record.revisit_on or "Not set"),
            ("Language", record.language),
            ("Direction", record.direction),
        ]
        page = output_dir / href
        page.write_text(
            decision_template.render(
                record=record,
                details=details,
                body_html=body_html,
                css=HTML_CSS,
                html_dir=html_direction(record),
                content_dir=html_direction(record),
            ),
            encoding="utf-8",
        )
        pages.append(page)

    index_path = output_dir / "index.html"
    index_path.write_text(
        index_template.render(records=index_items, css=HTML_CSS, config=config),
        encoding="utf-8",
    )
    return [index_path, *pages]
