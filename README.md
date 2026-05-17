# DecisionTrail

Git-native decision log for founders, product teams, and operators.

DecisionTrail is a local-first CLI for recording important product, business,
strategy, hiring, pricing, risk, and technical decisions as Markdown files with
YAML frontmatter. It gives decisions a durable shape: context, options,
rationale, assumptions, success metrics, evidence, metric updates, revisit dates,
and outcome reviews.
Every decision update creates a versioned sidecar snapshot so edits remain
traceable without making the current Markdown record hard to read.

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
decisiontrail list --status accepted --tag pricing
decisiontrail due
decisiontrail assumptions
decisiontrail search pricing
decisiontrail score
decisiontrail history DEC-2026-001
decisiontrail evidence add DEC-2026-001 "Margin sheet" --type url --ref https://example.com
decisiontrail metric add DEC-2026-001 gross_margin --value "42%" --measured-on 2026-08-01
decisiontrail drafts list
decisiontrail graph --format mermaid
decisiontrail run weekly-review
decisiontrail export --format html
decisiontrail ui
```

## Record format

Each decision is a Markdown file with English frontmatter keys:

```yaml
id: DEC-2026-001
title: Launch tiered pricing for high-volume merchants
decision_type: pricing
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
evidence:
  - title: Margin model
    type: file
    ref: ./analysis/margin-model.xlsx
    note: Local evidence reference only; files are not copied.
    added_on: 2026-05-20
metric_updates:
  - name: gross_margin
    value: 42%
    measured_on: 2026-06-01
    note: First cohort result.
revisit_on: 2026-07-15
tags:
  - pricing
  - growth
parent_id: ""
related_decisions:
  - id: DEC-2026-000
    type: informs
    note: Original pricing context
language: en
direction: auto
version: 1
created_at: "2026-05-11T10:00:00Z"
updated_at: "2026-05-11T10:00:00Z"
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
decisiontrail new "Tagged decision" --tag pricing --tag growth
decisiontrail list --status accepted --owner Product --tag pricing
decisiontrail due
decisiontrail assumptions
decisiontrail score DEC-2026-001
decisiontrail history DEC-2026-001
decisiontrail new "Launch partner pilot" --parent DEC-2026-001 --related depends_on:DEC-2026-002
decisiontrail relate DEC-2026-003 DEC-2026-001 --type informs --note "Pricing context"
decisiontrail links DEC-2026-001
decisiontrail tree
decisiontrail search "pricing margin" --view Pricing
decisiontrail graph --format json
decisiontrail diff DEC-2026-001 --from 1 --to current
decisiontrail restore DEC-2026-001 --version 1 --confirm-id DEC-2026-001
decisiontrail evidence add DEC-2026-001 "Experiment note" --type note --note "Cohort stayed healthy."
decisiontrail evidence list DEC-2026-001
decisiontrail metric add DEC-2026-001 gross_margin --value "42%" --measured-on 2026-08-01
decisiontrail metric list DEC-2026-001
decisiontrail views save "Pricing review" --q pricing
decisiontrail drafts list
decisiontrail drafts promote DRAFT-2026-001 --owner Product
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
reading version history, and guarded deletion. It also exposes `decisiontrail://schema`,
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
- a review inbox for due reviews, missing metrics, low scores, and open
  assumptions
- full-text search, built-in views, and private local saved views
- a local decision graph for parent/child hierarchy and typed links
- decision list filters by status, owner, and tag
- a form for creating new decision records with optional parent and typed links
- edit forms for updating frontmatter and Markdown body without changing the ID
  or filename; every edit creates a new version
- read-first decision detail pages that put the Markdown decision body before
  scorecards, audit warnings, relationship controls, reviews, and delete actions
- collapsed scorecard, parent/child links, outgoing links, computed backlinks,
  assumption controls, version history, and audit panels on the detail page
- evidence references and metric updates on each decision detail page
- history diffs and guarded restore-as-new-version from snapshots
- quick status changes and outcome review
- assumption verification with `unvalidated`, `pending`, `validated`, and
  `invalidated` statuses
- local audit, HTML export, draft inbox, and meeting-note parsing from the browser
- guarded delete for unreferenced decisions

Tags are stored in the existing `tags` frontmatter list and are matched as
trimmed, case-insensitive exact values. For example, `pricing` matches
`Pricing`, but `price` does not match `pricing`.

All UI labels are English. Content fields use `dir="auto"`, and record previews
honor each decision's `language` and `direction` metadata so Persian and mixed
RTL/LTR decisions render cleanly.

Delete is intentionally conservative: the UI hard-removes the Markdown file only
after the exact decision ID is typed, and it blocks deletion while the decision
has child decisions or incoming backlinks. A final version snapshot is written
before deletion. Recovery is expected to come from the local filesystem,
DecisionTrail history snapshots, or Git history.

## Version history

Current decision files stay in `decisions/`. Version snapshots are stored under
`.decisiontrail/history/<DECISION-ID>/` as full Markdown files:

```text
.decisiontrail/history/DEC-2026-001/v0001.md
.decisiontrail/history/DEC-2026-001/v0002.md
.decisiontrail/history/DEC-2026-001/events.jsonl
```

`events.jsonl` records the version, previous version, timestamp, source, action,
changed fields, and snapshot path for each change. New records start at
`version: 1`. Older records without version metadata are treated as v1; their first future
change captures a v1 baseline snapshot and writes the updated record as v2.

Versioned writes are shared by the web UI, CLI, and MCP server for edits, status
changes, assumption verification, relation changes, evidence and metric updates,
outcome reviews, restores, and guarded deletes. Restores are history-preserving:
an old snapshot is written back as a new current version instead of rewriting
past history.

## Evidence, metrics, drafts, and views

Evidence stores references only. DecisionTrail records URLs, local paths, notes,
or experiment references in YAML but does not copy files into the project.
Metric updates are measured observations attached to a decision; they complement
the target `success_metrics` list without replacing it.

Meeting notes and agent workflows can save private local drafts under
`.decisiontrail/drafts/`. Drafts can be promoted into real Markdown decisions or
deleted from the inbox. User-created saved views are private local data in
`.decisiontrail/views.json`; built-in views such as Due, Risk, AI, Pricing, and
Hiring are available without config.

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
records render cleanly. The exported index includes a local tag filter for
reviewing archived decisions by tag without a server.

```bash
decisiontrail export --format html --output site
```

## Development

```bash
uv run pytest
uv run decisiontrail --help
uv run decisiontrail run weekly-review
```
