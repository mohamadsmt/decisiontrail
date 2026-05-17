from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template


DEFAULT_DECISION_BODY_TEMPLATE = """# {{ title }}

## Context

{{ context or "TODO: Describe the situation that made this decision necessary." }}

## Options Considered

{% if options -%}
{% for option in options -%}
- {{ option }}
{% endfor -%}
{% else -%}
- TODO: Add the first option.
- TODO: Add the second option.
{% endif %}

## Decision

{{ decision or "TODO: State the selected option." }}

## Rationale

{% if rationale -%}
{% for item in rationale -%}
- {{ item }}
{% endfor -%}
{% else -%}
- TODO: Explain why this option was selected.
{% endif %}

## Assumptions

{% if assumptions -%}
{% for assumption in assumptions -%}
- {{ assumption.text if assumption is mapping else assumption }}
{% endfor -%}
{% else -%}
- TODO: Add the main assumption behind this decision.
{% endif %}

## Success Metrics

{% if success_metrics -%}
{% for metric in success_metrics -%}
- {{ metric }}
{% endfor -%}
{% else -%}
- TODO: Add at least one success metric.
{% endif %}

## Outcome Review

TODO: Add the measured outcome after the revisit date.
"""


HTML_INDEX_TEMPLATE = """<!doctype html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DecisionTrail</title>
  <style>{{ css }}</style>
</head>
<body>
  <main class="shell">
    <header class="page-header">
      <p class="eyebrow">DecisionTrail</p>
      <h1>Decision records</h1>
      <p><span data-record-count>{{ records|length }} records shown</span> · {{ records|length }} records exported locally.</p>
    </header>
    <form class="filter-bar" aria-label="Decision filters">
      <label for="tag-filter">Tag</label>
      <select id="tag-filter" data-tag-filter>
        <option value="">All tags</option>
        {% for tag in tag_options %}
        <option value="{{ tag.key }}">{{ tag.label }}</option>
        {% endfor %}
      </select>
    </form>
    <section class="record-grid" aria-label="Decision records">
      {% for item in records %}
      <article class="record-card" dir="auto" data-record-card data-tag-keys='{{ item.tag_keys|tojson }}'>
        <div class="meta-row">
          <span>{{ item.record.id }}</span>
          <span>{{ item.record.status }}</span>
        </div>
        <h2><a href="{{ item.href }}">{{ item.record.title }}</a></h2>
        {% if item.tags %}
        <div class="tag-list">
          {% for tag in item.tags %}
          <span class="tag-pill">{{ tag }}</span>
          {% endfor %}
        </div>
        {% endif %}
        <dl>
          <div><dt>Owner</dt><dd>{{ item.record.owner or "Unassigned" }}</dd></div>
          <div><dt>Parent</dt><dd>{% if item.parent %}{{ item.parent.id }}{% else %}None{% endif %}</dd></div>
          <div><dt>Children</dt><dd>{{ item.child_count }}</dd></div>
          <div><dt>Date</dt><dd>{{ item.record.decision_date or "Unknown" }}</dd></div>
          <div><dt>Revisit</dt><dd>{{ item.record.revisit_on or "Not set" }}</dd></div>
        </dl>
      </article>
      {% endfor %}
    </section>
  </main>
  <script>
    const tagFilter = document.querySelector("[data-tag-filter]");
    const recordCount = document.querySelector("[data-record-count]");
    const cards = Array.from(document.querySelectorAll("[data-record-card]"));
    function applyTagFilter() {
      const selectedTag = tagFilter.value;
      let visibleCount = 0;
      for (const card of cards) {
        const tagKeys = JSON.parse(card.dataset.tagKeys || "[]");
        const isVisible = !selectedTag || tagKeys.includes(selectedTag);
        card.hidden = !isVisible;
        if (isVisible) visibleCount += 1;
      }
      recordCount.textContent = `${visibleCount} records shown`;
    }
    tagFilter.addEventListener("change", applyTagFilter);
    applyTagFilter();
  </script>
</body>
</html>
"""


HTML_DECISION_TEMPLATE = """<!doctype html>
<html lang="{{ record.language }}" dir="{{ html_dir }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ record.id }} - {{ record.title }}</title>
  <style>{{ css }}</style>
</head>
<body>
  <main class="shell record-page" dir="{{ content_dir }}">
    <nav class="top-nav" dir="ltr"><a href="index.html">Decision records</a></nav>
    <article>
      <header class="page-header" dir="auto">
        <p class="eyebrow">{{ record.id }} · {{ record.status }}</p>
        <h1>{{ record.title }}</h1>
        {% if tags %}
        <div class="tag-list">
          {% for tag in tags %}
          <span class="tag-pill">{{ tag }}</span>
          {% endfor %}
        </div>
        {% endif %}
      </header>
      <section class="details" aria-label="Decision metadata">
        {% for label, value in details %}
        <div dir="auto"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
        {% endfor %}
      </section>
      <section class="relationship-grid" aria-label="Decision relationships">
        <div class="relationship-panel">
          <h2>Hierarchy</h2>
          <dl>
            <div>
              <dt>Parent</dt>
              <dd>
                {% if parent %}
                <a href="{{ hrefs_by_id[parent.id] }}">{{ parent.id }}</a> <span dir="auto">{{ parent.title }}</span>
                {% else %}
                None
                {% endif %}
              </dd>
            </div>
            <div>
              <dt>Children</dt>
              <dd>
                <ul class="link-list">
                  {% for child in children %}
                  <li><a href="{{ hrefs_by_id[child.id] }}">{{ child.id }}</a> <span dir="auto">{{ child.title }}</span></li>
                  {% else %}
                  <li>No child decisions.</li>
                  {% endfor %}
                </ul>
              </dd>
            </div>
          </dl>
        </div>
        <div class="relationship-panel">
          <h2>Typed links</h2>
          <dl>
            <div>
              <dt>Outgoing</dt>
              <dd>
                <ul class="link-list">
                  {% for relation in outgoing_relations %}
                  {% set target = records_by_id.get(relation.target_id) %}
                  <li>
                    <strong>{{ relation.relation_type|replace("_", " ") }}</strong>
                    {% if target %}
                    <a href="{{ hrefs_by_id[target.id] }}">{{ target.id }}</a> <span dir="auto">{{ target.title }}</span>
                    {% else %}
                    <span>{{ relation.target_id }}</span>
                    {% endif %}
                    {% if relation.note %}<small dir="auto">{{ relation.note }}</small>{% endif %}
                  </li>
                  {% else %}
                  <li>No outgoing links.</li>
                  {% endfor %}
                </ul>
              </dd>
            </div>
            <div>
              <dt>Linked from</dt>
              <dd>
                <ul class="link-list">
                  {% for relation in backlinks %}
                  {% set source = records_by_id.get(relation.source_id) %}
                  <li>
                    <strong>{{ relation.relation_type|replace("_", " ") }}</strong>
                    {% if source %}
                    <a href="{{ hrefs_by_id[source.id] }}">{{ source.id }}</a> <span dir="auto">{{ source.title }}</span>
                    {% else %}
                    <span>{{ relation.source_id }}</span>
                    {% endif %}
                    {% if relation.note %}<small dir="auto">{{ relation.note }}</small>{% endif %}
                  </li>
                  {% else %}
                  <li>No backlinks.</li>
                  {% endfor %}
                </ul>
              </dd>
            </div>
          </dl>
        </div>
      </section>
      <section class="body" dir="auto">
        {{ body_html|safe }}
      </section>
    </article>
  </main>
</body>
</html>
"""


HTML_CSS = """
:root {
  color-scheme: light;
  --bg: #f7f4ee;
  --surface: #ffffff;
  --text: #1d2525;
  --muted: #697272;
  --line: #d9d6cf;
  --accent: #176b5b;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.6;
}

a { color: var(--accent); text-decoration-thickness: 0.08em; text-underline-offset: 0.2em; }

.shell {
  width: min(1080px, calc(100% - 32px));
  margin-inline: auto;
  padding-block: 40px 64px;
}

.page-header {
  border-block-end: 1px solid var(--line);
  padding-block-end: 24px;
  margin-block-end: 24px;
}

.eyebrow {
  color: var(--muted);
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1, h2, h3 { line-height: 1.2; letter-spacing: 0; }
h1 { font-size: clamp(2rem, 4vw, 3.4rem); margin: 0; }
h2 { font-size: 1.2rem; margin-block: 12px; }

.record-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}

.filter-bar {
  align-items: center;
  display: flex;
  gap: 10px;
  margin-block-end: 18px;
}

.filter-bar label {
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 700;
}

.filter-bar select {
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--text);
  font: inherit;
  min-height: 38px;
  padding: 8px 10px;
}

.record-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}

.record-card[hidden] {
  display: none;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 0.86rem;
}

.tag-list {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-block: 10px;
}

.tag-pill {
  background: #eef8f4;
  border: 1px solid #cde7df;
  border-radius: 999px;
  color: var(--accent);
  display: inline-flex;
  font-size: 0.76rem;
  font-weight: 680;
  line-height: 1;
  padding: 5px 8px;
}

dl, .details {
  display: grid;
  gap: 10px;
}

.details {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-block-end: 28px;
}

dt {
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
}

dd { margin: 0; }

.body {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: clamp(18px, 4vw, 34px);
}

.body h1:first-child { display: none; }
.body p, .body li { max-width: 76ch; }
.body blockquote {
  margin-inline: 0;
  padding-inline-start: 1rem;
  border-inline-start: 4px solid var(--accent);
  color: var(--muted);
}

.top-nav { margin-block-end: 24px; }

.relationship-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin-block-end: 28px;
}

.relationship-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}

.relationship-panel h2 {
  margin-block-start: 0;
}

.link-list {
  margin: 0;
  padding-inline-start: 1.2rem;
}

.link-list li {
  display: grid;
  gap: 3px;
  padding-block: 5px;
}

.link-list small {
  color: var(--muted);
}
"""


def render_decision_body(root: Path, templates_dir: str, context: dict[str, Any]) -> str:
    template_path = root / templates_dir / "decision.md.j2"
    if template_path.exists():
        env = Environment(loader=FileSystemLoader(template_path.parent), autoescape=False)
        template = env.get_template(template_path.name)
        return template.render(**context).strip() + "\n"
    return Template(DEFAULT_DECISION_BODY_TEMPLATE).render(**context).strip() + "\n"
