from __future__ import annotations

from pathlib import Path

from jinja2 import Template
from markdown import markdown

from decisiontrail.config import DecisionTrailConfig
from decisiontrail.models import DecisionRecord
from decisiontrail.relationships import backlinks, children_of, outgoing_relations
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
    records_by_id = {record.id: record for record in records}
    hrefs_by_id = {record.id: decision_href(record) for record in records}
    for record in records:
        href = hrefs_by_id[record.id]
        parent = records_by_id.get(record.parent_id) if record.parent_id else None
        children = children_of(records, record.id)
        index_items.append({"record": record, "href": href, "parent": parent, "child_count": len(children)})
        body_html = markdown(record.body, extensions=["fenced_code", "tables"])
        details = [
            ("Owner", record.owner or "Unassigned"),
            ("Parent", record.parent_id or "None"),
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
                records_by_id=records_by_id,
                hrefs_by_id=hrefs_by_id,
                parent=parent,
                children=children,
                outgoing_relations=outgoing_relations(record),
                backlinks=backlinks(records, record.id),
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
