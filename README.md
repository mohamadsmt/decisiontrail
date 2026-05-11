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
decisiontrail review DEC-2026-001 --outcome "Gross margin improved without retention loss."
decisiontrail parse-meeting notes/weekly.md
decisiontrail export --format html
decisiontrail check
decisiontrail run weekly-review
decisiontrail run audit
decisiontrail run export-html
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
