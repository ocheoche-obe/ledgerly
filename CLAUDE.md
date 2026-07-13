# Ledgerly — Project Context for Claude Code

> This file is loaded at the start of every Claude Code session. Keep it current
> as the project evolves. The phase marker at the bottom is especially important.

## How this project is run

Built with agentic-engineering discipline: a six-stage lifecycle run as a cycle —
**Requirements → Architecture → Implementation → Testing → Deployment → Evaluation →
(loop)** — and a doc set where each document owns exactly one of the six questions
(**who/what** = requirements, **where/how** = architecture, **why** = ADL, **when** = plan).
See `KICKOFF.md` for the full framework.

## What this app does

Ledgerly is a personal budgeting app for its owner (single user). It ingests bank
transaction history (CSV import in v1; Plaid live sync deferred), an AI agent categorizes
every transaction into owner-defined budget categories, and a dashboard shows budget vs.
actual per category at a glance for each budget cycle (calendar month by default, or a
two-week payday-aligned cycle). Secondary purpose: an explicit learning vehicle for
AI/LLM pipelines, AWS serverless, IaC/CI-CD, and full-stack skills.

Single-user MVP, data model designed to be multi-tenant-ready (ADR-006).
Deployment: AWS, serverless-first (ADR-001).

## Canonical docs (always trust these first)

- **`docs/ledgerly-architecture.md`** — full architecture document. Authoritative
  source for system design, data model, sequence diagrams, cross-cutting concerns, IaC.
- **`docs/ledgerly-plan.md`** — implementation plan & roadmap. Authoritative for
  slice order, per-slice scope/exit criteria, status, and completion notes.
- **`docs/ledgerly-requirements.md`** — functional and non-functional requirements.
- **`docs/ledgerly-adl.md`** — Architectural Decision Records. The "why" behind
  every significant choice.
- **`docs/ledgerly-evaluation.md`** — lifecycle stage 6: metrics, retrospectives,
  and the findings that seed the next cycle.
- **`docs/ledgerly-glossary.md`** — terms, services, cross-cloud parallels.
- **`docs/ledgerly-reference.md`** — original scoping notes / brain-dump (frozen).

When making implementation decisions, consult the architecture doc first. If something
seems off or unclear, the ADL captures the reasoning behind it.

## Architecture summary

_Approved 2026-07-13 (architecture doc v1.1; ADR-001…009 all Accepted):_

- **Deployment:** AWS us-east-1, serverless-first (ADR-001); one account, `dev` + `prod`
  CDK stages.
- **Stack:** Python 3.13 Lambdas (ADR-002) · React+Vite+TS SPA on S3/CloudFront
  (ADR-003) · CDK in Python (ADR-004) · DynamoDB single table, access-pattern-first,
  cycle-keyed budgets (ADR-005) · `USER#<sub>` partition scoping, multi-tenant-ready
  (ADR-006) · Cognito + API Gateway HTTP API JWT authorizer (ADR-007).
- **AI pipeline:** SQS + DLQ (ADR-009) → categorizer Lambda → merchant rules first, then
  Claude Opus 4.8 via Amazon Bedrock with structured output (ADR-008). **Zero runtime
  secrets** — everything is IAM-role auth.
- **Key data-model idea:** everything keyed by user + budget cycle (`M#2026-07` /
  `B#2026-07-10`); cycle windows derived from settings, so cadence changes never rewrite
  history. Diagram: `docs/ledgerly-architecture-diagram.png` (regenerate via
  `docs/render_architecture.py` — diagram as code).

## Components / functions

_None yet — filled in during Phase 1/first slices._

## Repository layout

```
docs/                # Canonical docs: requirements, architecture, ADL, plan, evaluation, glossary, reference
.claude/skills/      # /start-slice and /wrap-slice session rituals
CLAUDE.md            # This file
KICKOFF.md           # The reusable agentic-engineering framework (leave untouched)
```

## Conventions

_To solidify at the end of the first implementation slice. Already binding:_

- User identity comes from the auth token, never the request body (FR-1.3); secrets
  never in code/repo (NFR-4.3); all infra as code (NFR-5.1).
- **Diagram as code:** architecture diagrams are generated from
  `docs/render_architecture.py` (mingrammer) — re-render in the same commit as any
  system-shape change.
- Business logic lives in `backend/core/` with no AWS imports; handlers stay thin
  (architecture §5.2).
- Review `cdk diff` before every deploy (ADR-004 learning habit).

## Cost constraints

- **$10/month effective hard ceiling** (NFR-1.1) — single-user personal app; serverless
  keeps idle cost near zero. Plaid production would be a deliberate ADR-recorded revision.
- Guards in place: none yet — AWS Budgets alarm ($5 actual / $8 forecast) ships in
  Slice 1 (NFR-1.2). Bedrock spend rides the same AWS bill, so the alarm covers LLM cost
  too (ADR-008). Expected steady state ≈ $2–4/month total.

## Current build phase

**Phase 1 — complete (2026-07-13). Current slice: Slice 1 — walking skeleton
(not started; begin with `/start-slice` in a fresh session).**

- Last completed: P1 Architecture — architecture approved v1.1 (2026-07-13, owner
  review; one amendment: rendered diagrams-as-code architecture diagram), ADR-002…009
  Accepted, slice roadmap 1–8 owner-approved (walking skeleton → CI/CD → categories/
  cycle engine → CSV import → AI categorization → dashboard → review queue → hardening).
- **The roadmap lives in `docs/ledgerly-plan.md`** — slice order, per-slice scope,
  exit criteria, open decisions, and completion notes. Read the status board + current
  slice section at session start; update it when a slice wraps.
- Session rituals: `/start-slice` and `/wrap-slice` (project skills in `.claude/skills/`).

Refer to the architecture doc as you implement. If a decision needs to be made that isn't
covered, capture it as a new ADR in `ledgerly-adl.md` before coding it in.
