# DecisionTrail

Git-native decision log for founders, product teams, and operators.

DecisionTrail is a local-first CLI for recording important product, business,
strategy, hiring, pricing, risk, and technical decisions as Markdown files with
YAML frontmatter. It gives decisions a durable shape: context, options,
rationale, assumptions, success metrics, revisit dates, and outcome reviews.

The product language is English. Decision content can be English, Persian, or
mixed RTL/LTR text.

## Why it exists

Teams often remember what they decided, but lose the reason behind it:

- Why was this option selected?
- Which alternatives were rejected?
- What assumption carried the decision?
- Which metric was supposed to prove it worked?
- When should the decision be revisited?
- Did the decision actually work?

DecisionTrail keeps those answers close to the work. Records are plain UTF-8
Markdown files, so they work in a normal folder, a private repository, or any
Git workflow without a hosted service.

## Install for development

```bash
uv sync
uv run decisiontrail --help
```

## Quick start

```bash
decisiontrail init
decisiontrail new "Launch tiered pricing" --owner "Product"
decisiontrail list --status accepted
decisiontrail due
decisiontrail assumptions
decisiontrail score
decisiontrail run weekly-review
decisiontrail export --format html
decisiontrail ui
```

## Record format

Each decision is a Markdown file with English frontmatter keys:

```yaml
id: DEC-2026-001
title: Launch tiered pricing for high-volume merchants
status: accepted
date: 2026-05-11
owner: Product
context: Current pricing creates margin pressure for high-volume merchants.
options:
  - Keep current pricing
  - Increase flat fee
  - Launch tiered pricing
decision: Launch tiered pricing
rationale:
  - Better margin control
  - Lower churn risk than flat fee increase
assumptions:
  - text: High-volume merchants care more about reliability than small fee changes.
    status: unvalidated
success_metrics:
  - gross_margin
  - merchant_retention
revisit_on: 2026-07-15
parent_id: ""
related_decisions:
  - id: DEC-2026-000
    type: informs
    note: Original pricing context
language: en
direction: auto
```

Persian content is stored directly as UTF-8:

```yaml
title: تغییر مدل قیمت‌گذاری برای فروشنده‌های بزرگ
language: fa
direction: rtl
```

Use `direction: auto` for mixed English/Persian records, `rtl` for Persian-first
records, and `ltr` for English-first records.

## Commands

```bash
decisiontrail init
decisiontrail new "Decision title"
decisiontrail list --status accepted --owner Product
decisiontrail due
decisiontrail assumptions
decisiontrail score DEC-2026-001
decisiontrail new "Launch partner pilot" --parent DEC-2026-001 --related depends_on:DEC-2026-002
decisiontrail relate DEC-2026-003 DEC-2026-001 --type informs --note "Pricing context"
decisiontrail links DEC-2026-001
decisiontrail tree
decisiontrail review DEC-2026-001 --outcome "Gross margin improved without retention loss."
decisiontrail parse-meeting notes/weekly.md
decisiontrail export --format html
decisiontrail check
decisiontrail ui --path . --host 127.0.0.1 --port 8765
decisiontrail run weekly-review
decisiontrail run audit
decisiontrail run export-html
```

## Agent MCP server

DecisionTrail can expose the same local Markdown/YAML decision workflow to
agentic tools through MCP. The server is local-first and uses the current
project folder unless `--path` or `DECISIONTRAIL_ROOT` is set.

For Codex-style stdio clients:

```bash
decisiontrail-mcp --path .
```

For local Streamable HTTP clients:

```bash
decisiontrail-mcp --path . --transport streamable-http --host 127.0.0.1 --port 8766 --path-prefix /mcp
```

The MCP server provides tools for listing, searching, reading, creating,
updating, relating, reviewing, auditing, parsing meeting notes, exporting HTML,
and guarded deletion. It also exposes `decisiontrail://schema`,
`decisiontrail://workflow-guide`, and a `capture_decision_from_rough` prompt so
agents can turn rough product or business decisions into complete records and
then audit the result.

## Local web UI

DecisionTrail includes a localhost-only browser UI for adding and reviewing
decision records without leaving the local project folder:

```bash
decisiontrail ui
```

The UI runs at `http://127.0.0.1:8765` by default and writes the same
Markdown/YAML files as the CLI. It includes:

- dashboard summaries for due reviews, missing metrics, low scores, and
  unvalidated assumptions
- decision list filters by status and owner
- a form for creating new decision records with optional parent and typed links
- edit forms for updating frontmatter and Markdown body without changing the ID
  or filename
- decision detail pages with scorecards, parent/child links, outgoing links,
  computed backlinks, and Markdown preview
- quick status changes and outcome review
- assumption verification with `unvalidated`, `pending`, `validated`, and
  `invalidated` statuses
- local audit, HTML export, and meeting-note parsing from the browser
- guarded delete for unreferenced decisions

All UI labels are English. Content fields use `dir="auto"`, and record previews
honor each decision's `language` and `direction` metadata so Persian and mixed
RTL/LTR decisions render cleanly.

Delete is intentionally conservative: the UI hard-removes the Markdown file only
after the exact decision ID is typed, and it blocks deletion while the decision
has child decisions or incoming backlinks. Recovery is expected to come from the
local filesystem or Git history.

## Relationships

DecisionTrail supports one hierarchical parent plus directed typed links.
Backlinks are computed from all local records and are never written into the
target decision file.

```yaml
parent_id: DEC-2026-001
related_decisions:
  - id: DEC-2026-002
    type: depends_on
    note: Required before launch
```

Supported relation types are `related_to`, `depends_on`, `blocks`,
`supersedes`, and `informs`.

Create child and related decisions from the CLI:

```bash
decisiontrail new "Define enterprise pricing pilot" --parent DEC-2026-001
decisiontrail new "Launch partner pilot" --related depends_on:DEC-2026-001
decisiontrail relate DEC-2026-003 DEC-2026-001 --type informs --note "Pricing context"
decisiontrail links DEC-2026-001
decisiontrail tree
```

The local web UI includes a parent dropdown, an `Add child decision` flow from a
decision detail page, a related-decision textarea that accepts one relation per
line, and detail-page controls for adding or removing outgoing relations:

```text
depends_on: DEC-2026-001 | optional note
informs: DEC-2026-002
```

## Internal actions

DecisionTrail includes local actions that can be run by humans, cron, shell
scripts, or any generic CI runner:

- `decisiontrail run weekly-review` reports overdue decisions, missing metrics,
  unvalidated assumptions, and decisions that need an outcome review.
- `decisiontrail run audit` validates structure, score quality, overdue policy,
  and RTL metadata consistency.
- `decisiontrail run export-html` builds a static local archive.

By default checks warn without failing. Use strict flags when you want a
non-zero exit code:

```bash
decisiontrail check --fail-on-overdue --fail-under-score
decisiontrail run audit --fail-on-overdue --fail-under-score
```

## HTML export and RTL support

HTML export writes local static pages to `site/`. Generated pages use `lang`,
`dir`, `dir="auto"`, and CSS logical properties so Persian, English, and mixed
records render cleanly.

```bash
decisiontrail export --format html --output site
```

## Development

```bash
uv run pytest
uv run decisiontrail --help
uv run decisiontrail run weekly-review
```
