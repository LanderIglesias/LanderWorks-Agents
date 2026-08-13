# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Lander Iglesias — the sole user, permanently. This is a personal tool, not a
multi-tenant product: no accounts system, no signup, a single static app
token instead of login. Situation: an expense just happened (paid with
Apple Pay, a bank card charge, a PayPal payment) or he wants to log one
manually. Job: glance at the total for the day/month/year, and clear the
review queue for the handful of entries automation couldn't parse
confidently.

## Product Purpose

Automatic, low-friction personal expense tracking that captures spend from
real-world channels — an Apple Wallet transaction trigger, a bank
notification email, a PayPal notification email — via iOS Shortcuts
automations calling a webhook, so Lander doesn't have to manually log every
purchase. Manual entry from the PWA is a guaranteed fallback, not an
afterthought: no expense is ever silently lost even when automation fails.
Success = every real expense ends up in the ledger, duplicates from the
same purchase collapse into one row, and most rows need zero manual
correction.

## Positioning

Not a general-purpose budgeting SaaS. A single-user automation tightly
coupled to Lander's actual bank (Laboral Kutxa) and card, deployed on his
own EC2. What a generic budgeting app couldn't truthfully copy: dual-channel
confirmation for the same Apple Pay purchase (Wallet trigger + bank email
notification, deduplicated into one row instead of double-counting) and a
manual-entry floor that exists specifically because Apple's own Shortcuts
"Transaction" trigger has documented, unresolved bugs (FB14035016,
FB16379100) that can fail silently — the app is designed assuming its
primary automation channel will sometimes just not fire.

## Operating Context

Three iOS Shortcuts automations (Wallet transaction, Laboral Kutxa email,
PayPal email) call `POST /webhook/expense` with Bearer-token + ISO-8601
timestamp auth, no user present at call time. The PWA is opened from the
iPhone home screen (installed via Safari "Add to Home Screen") for
reviewing totals, clearing the needs-review queue, and manual entry — a
human is always present for that half. Backend is FastAPI + PostgreSQL
behind Cloudflare, deployed as its own lightweight Docker image on the same
EC2 as other unrelated portfolio agents (see Capabilities). Claude Haiku
categorizes each expense once at ingest time, not on every read.

## Capabilities and Constraints

- `amount` can be `null` (`needs_review=true`) when email parsing fails —
  the row is always saved with `raw_text` intact; a $0 placeholder is never
  invented, since that would be indistinguishable from a real €0 expense in
  aggregate totals.
- Wallet and bank-email events for the same real Apple Pay purchase are
  deduplicated (same amount, opposite channel, ±90s window) into a single
  row rather than double-counted.
- Webhook auth is Bearer token + ISO-8601 timestamp (not HMAC — iOS
  Shortcuts has no native action to compute one), rate-limited to 20
  requests/minute.
- The PWA's own auth is a separate static Bearer token, entered once and
  stored in `localStorage` — deliberately simpler than the webhook's
  scheme, because a human is present at that call site.
- Categories are a fixed list (comida, transporte, suscripciones, ocio,
  salud, hogar, otros); categorization confidence below 0.6 forces
  `needs_review=true` regardless of source.
- No accounts, roles, or permissions model — by design, not an unfinished
  feature.

## Brand Commitments

App name is "Gastos" (PWA manifest `name`/`short_name`). No pre-existing
logo or brand identity beyond that name — icons currently in
`static/icons/` are functional placeholders, not a committed mark. Visual
direction (color, materials, motion) is being decided separately and is out
of scope for this file.

## Evidence on Hand

A working backend and PWA already exist at `backend/agents/expense_tracker/`
— real endpoints, real Postgres schema, real Shortcuts integration
documented step-by-step in `README_expense_tracker.md`. No user research and
no real usage screenshots exist yet; future design work must not fabricate
metrics, testimonials, or sample data beyond what the real schema/endpoints
actually return.

## Product Principles

1. Never lose an expense — a parsing or automation failure degrades to
   `needs_review`, never silent data loss.
2. Manual entry is a first-class safety net, not an afterthought — it
   exists because the primary automation channel (Wallet) is known to be
   unreliable.
3. Minimize manual-correction burden, but the review queue is the honest
   fallback when categorization confidence is low — never fake confidence
   to hide it.
4. Single-user by design. No multi-tenant complexity, accounts, or
   permissions model to design around, now or later.
5. Real financial data only — the live app never shows mock or demo data.

## Accessibility & Inclusion

No product-specific accessibility requirement has been established beyond
standard iOS Safari/PWA behavior. Single sighted user; revisit if that
changes.
