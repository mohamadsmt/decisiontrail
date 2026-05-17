from __future__ import annotations

import html
import json
from typing import Callable, Any

from decisiontrail.models import DecisionRecord
from decisiontrail.relationships import outgoing_relations


def graph_data(records: list[DecisionRecord]) -> dict[str, list[dict[str, Any]]]:
    records_by_id = {record.id: record for record in records}
    nodes = [
        {
            "id": record.id,
            "title": record.title,
            "status": record.status,
            "owner": record.owner,
            "parent_id": record.parent_id,
        }
        for record in records
    ]
    edges: list[dict[str, str]] = []
    for record in records:
        if record.parent_id:
            edges.append(
                {
                    "source": record.parent_id,
                    "target": record.id,
                    "type": "child",
                    "note": "",
                    "valid": str(record.parent_id in records_by_id).lower(),
                }
            )
        for relation in outgoing_relations(record):
            edges.append(
                {
                    "source": record.id,
                    "target": relation.target_id,
                    "type": relation.relation_type,
                    "note": relation.note,
                    "valid": str(relation.target_id in records_by_id).lower(),
                }
            )
    return {"nodes": nodes, "edges": edges}


def graph_json(records: list[DecisionRecord]) -> str:
    return json.dumps(graph_data(records), ensure_ascii=False, indent=2)


def graph_mermaid(records: list[DecisionRecord]) -> str:
    lines = ["flowchart TD"]
    for record in records:
        label = f"{record.id}<br/>{record.title}".replace('"', "'")
        lines.append(f'  {record.id.replace("-", "_")}["{label}"]')
    for edge in graph_data(records)["edges"]:
        source = edge["source"].replace("-", "_")
        target = edge["target"].replace("-", "_")
        label = edge["type"].replace("_", " ")
        lines.append(f'  {source} -->|"{label}"| {target}')
    return "\n".join(lines) + "\n"


def _depths(records: list[DecisionRecord]) -> dict[str, int]:
    by_id = {record.id: record for record in records}
    cache: dict[str, int] = {}

    def depth(record: DecisionRecord, seen: set[str]) -> int:
        if record.id in cache:
            return cache[record.id]
        if not record.parent_id or record.parent_id not in by_id or record.id in seen:
            cache[record.id] = 0
            return 0
        value = min(depth(by_id[record.parent_id], seen | {record.id}) + 1, 4)
        cache[record.id] = value
        return value

    for record in records:
        depth(record, set())
    return cache


def graph_svg(records: list[DecisionRecord], *, href_for: Callable[[str], str] | None = None) -> str:
    if not records:
        return '<svg class="decision-graph" viewBox="0 0 640 120" role="img" aria-label="Decision graph"></svg>'
    href_for = href_for or (lambda decision_id: f"/decisions/{decision_id}")
    depths = _depths(records)
    positions: dict[str, tuple[int, int]] = {}
    width = 980
    row_height = 88
    height = max(160, 40 + row_height * len(records))
    for index, record in enumerate(records):
        x = 48 + depths.get(record.id, 0) * 180
        y = 32 + index * row_height
        positions[record.id] = (x, y)

    edge_lines: list[str] = []
    for edge in graph_data(records)["edges"]:
        source = positions.get(edge["source"])
        target = positions.get(edge["target"])
        if not source or not target:
            continue
        sx, sy = source
        tx, ty = target
        stroke = "#176b5b" if edge["type"] == "child" else "#7d8a85"
        edge_lines.append(
            f'<path d="M {sx + 220} {sy + 26} C {sx + 280} {sy + 26}, {tx - 60} {ty + 26}, {tx} {ty + 26}" '
            f'stroke="{stroke}" stroke-width="1.5" fill="none" marker-end="url(#arrow)" />'
        )
        edge_lines.append(
            f'<text x="{(sx + tx) / 2 + 90:.0f}" y="{(sy + ty) / 2 + 18:.0f}" class="graph-edge-label">{html.escape(edge["type"].replace("_", " "))}</text>'
        )

    node_lines: list[str] = []
    for record in records:
        x, y = positions[record.id]
        title = html.escape(record.title)
        status = html.escape(record.status)
        href = html.escape(href_for(record.id), quote=True)
        node_lines.append(
            f'<a href="{href}"><g class="graph-node">'
            f'<rect x="{x}" y="{y}" width="220" height="58" rx="7" />'
            f'<text x="{x + 12}" y="{y + 22}" class="graph-node-id">{html.escape(record.id)} · {status}</text>'
            f'<text x="{x + 12}" y="{y + 43}" class="graph-node-title">{title}</text>'
            f"</g></a>"
        )

    return (
        f'<svg class="decision-graph" viewBox="0 0 {width} {height}" role="img" aria-label="Decision graph">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto">'
        '<path d="M0,0 L8,3.5 L0,7 Z" fill="#7d8a85" /></marker></defs>'
        + "".join(edge_lines)
        + "".join(node_lines)
        + "</svg>"
    )
