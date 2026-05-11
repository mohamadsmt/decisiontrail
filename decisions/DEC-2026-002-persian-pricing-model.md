---
id: DEC-2026-002
title: تغییر مدل قیمت‌گذاری برای فروشنده‌های بزرگ
status: proposed
date: 2026-05-11
owner: CEO
context: این تصمیم برای کاهش فشار روی gross margin و حفظ retention بررسی می‌شود.
options:
- حفظ قیمت فعلی
- افزایش کارمزد ثابت
- ساخت پلن tiered
decision: ساخت پلن tiered برای segment فروشنده‌های بزرگ
rationale:
- ریسک churn کمتر از افزایش مستقیم قیمت است.
- امکان تست محدود روی segment مشخص وجود دارد.
assumptions:
- text: فروشنده‌های بزرگ نسبت به reliability حساس‌تر از تغییر کوچک fee هستند.
  status: unvalidated
success_metrics:
- gross_margin
- merchant_retention
revisit_on: 2026-07-15
outcome: ''
reviewed_on: ''
experiment_links: []
tags:
- pricing
- persian
language: fa
direction: rtl
---
# تغییر مدل قیمت‌گذاری برای فروشنده‌های بزرگ

## Context

این تصمیم برای کاهش فشار روی gross margin و حفظ retention بررسی می‌شود.

## Options Considered

- حفظ قیمت فعلی
- افزایش کارمزد ثابت
- ساخت پلن tiered

## Decision

ساخت پلن tiered برای segment فروشنده‌های بزرگ

## Rationale

- ریسک churn کمتر از افزایش مستقیم قیمت است.
- امکان تست محدود روی segment مشخص وجود دارد.

## Assumptions

- فروشنده‌های بزرگ نسبت به reliability حساس‌تر از تغییر کوچک fee هستند.

## Success Metrics

- gross_margin
- merchant_retention

## Outcome Review

TODO: Add the measured outcome after the revisit date.
