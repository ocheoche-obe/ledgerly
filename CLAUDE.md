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

## AWS account & profile

Ledgerly has its **own dedicated AWS account** (ADR-010), separate from other projects that
share the same SSO login. Pin these:

- **Account:** `816020558700` · **Region:** `us-east-1` · **Profile:** `ledgerly-dev`

**Rule: always prefix AWS/CDK/SAM commands with `AWS_PROFILE=ledgerly-dev` (or pass
`--profile ledgerly-dev`); never rely on a default profile.** A different project
(CareerVault, `768396678224`) shares this SSO login, so a bare profile can silently hit the
wrong account. Guards enforcing this: a SessionStart hook (`.claude/check-aws-profile.sh`)
asserts the account at session start; `/start-slice` re-asserts it and stops on mismatch;
and `infra/app.py` pins the account so a wrong-account `cdk deploy` fails fast.

## Components / functions

_Seeded in Slice 1 (walking skeleton); grows per slice._

- **`backend/core/`** — pure domain logic, **no AWS imports** (portability seam + unit-test
  surface). `settings.py`: default monthly PROFILE + projection. `cycles.py`: budget-cycle
  engine (FR-4.2) — cycle IDs/windows derived from the cadence history, clamped so no cycle
  straddles a cadence change; `plan_cadence_change` = change-effective-next-cycle.
  `categories.py`: category shape/validation + starter set (FR-4.4). `ids.py`: stdlib ULID
  (no runtime deps — the Lambda asset has no `pip` step).
- **`backend/adapters/`** — AWS-facing persistence (boto3). `dynamo.py`:
  `get_or_create_settings` (AP #1), `update_cadence` (FR-4.2), `list/create/update_category`
  (AP #2/#3, starters seeded once on first list).
- **`backend/functions/api_settings/handler.py`** — `GET`/`PATCH /settings` Lambda (returns
  the live current cycle); `backend/functions/api_categories/handler.py` — `GET`/`POST
  /categories` + `PATCH /categories/{id}`. Both: identity from verified JWT claims only (FR-1.3).
- **`infra/` (CDK, Python)** — `LedgerlyStack` (per-stage `Ledgerly-dev`/`Ledgerly-prod`) =
  constructs: `Data` (DynamoDB single table + GSI1/GSI2, PITR), `Auth` (Cognito pool +
  Hosted-UI/PKCE client + owner user), `Api` (HTTP API + JWT authorizer + settings &
  categories Lambdas via a shared `_api_lambda` helper, each with a least-privilege
  table-scoped role), `Web` (private S3 + CloudFront + runtime `config.json`), `Ops` (AWS
  Budgets billing alarm). Ingest + Categorization arrive in Slices 4–5. Separately,
  `LedgerlyCicdStack` (`Ledgerly-cicd`, account-global, deployed once) = `Cicd` construct:
  GitHub OIDC provider + narrow `ledgerly-github-deploy` role (ADR-011).
- **`.github/` (CI/CD)** — `checks.yml` (reusable test/lint/synth gate) called by `ci.yml`
  (PRs) and `deploy.yml` (push to `main` → deploy `dev`, then manual-approved `prod` via the
  `cdk-deploy` composite action); `codeql.yml` (SAST); `dependabot.yml`.
- **`frontend/` (React+Vite+TS)** — Hosted-UI PKCE login, fetches runtime `/config.json`.
  `api.ts` = typed client (bearer token on every call). `SettingsPanel` = cadence + current
  cycle; `CategoriesPanel` = category CRUD; `styles.ts` = shared inline styles.

## Repository layout

```
docs/                # Canonical docs: requirements, architecture, ADL, plan, evaluation, glossary, reference
.claude/skills/      # /start-slice and /wrap-slice session rituals
CLAUDE.md            # This file
KICKOFF.md           # The reusable agentic-engineering framework (leave untouched)
```

## Conventions

_Solidified at the end of Slice 1. Binding:_

- User identity comes from the auth token, never the request body (FR-1.3); secrets
  never in code/repo/logs (NFR-4.3); all infra as code (NFR-5.1).
- **Portability seam:** business logic in `backend/core/` has **no AWS imports** (the
  unit-test surface); boto3/AWS lives in `backend/adapters/`; `functions/` handlers stay
  thin (architecture §5.2).
- **AWS profile:** always `AWS_PROFILE=ledgerly-dev` (account `816020558700`) — never a
  default profile (ADR-010; see "AWS account & profile").
- **Diagram as code:** re-render `docs/render_architecture.py` in the same commit as any
  system-shape change.
- Review `cdk diff` before every deploy (ADR-004 learning habit).
- **Lint/test:** `ruff check backend infra` (config `ruff.toml`); `pytest` (backend);
  `npm run build`/`test` (frontend). CI runs all on PR (`.github/workflows/ci.yml`).
- **Security gate:** `/security-review` is a blocking pre-commit step every slice; CodeQL +
  Dependabot are the remote net on PRs.
- **Code review:** `/code-review medium` runs at `/wrap-slice` (step 3) as an **advisory**
  (non-blocking) correctness pass — adopted Slice 3 after a trial found real bugs CI + tests
  + security-review missed. Triage findings; a false positive never blocks a slice.

## Cost constraints

- **$10/month effective hard ceiling** (NFR-1.1) — single-user personal app; serverless
  keeps idle cost near zero. Plaid production would be a deliberate ADR-recorded revision.
- Guards in place: **AWS Budgets alarm live** ($5 actual / $8 forecast) as of Slice 1
  (NFR-1.2); the dedicated account (ADR-010) makes the account bill == Ledgerly spend.
  Bedrock spend rides the same AWS bill, so the alarm covers LLM cost too (ADR-008).
  Expected steady state ≈ $2–4/month total.

## Current build phase

**Slice 3 — Categories, settings & budget-cycle engine: complete & deployed (2026-07-19),
PR [#21] merged (dev + prod). Next: Slice 4 — CSV import end-to-end (needs the owner's sample
bank CSV exports at slice start — see plan Slice 4 ⚠).**

- Last completed: Slice 3 — `core/cycles.py` budget-cycle engine (cycle IDs/windows from the
  cadence history, clamped so no cycle straddles a change; change-effective-next-cycle,
  FR-4.2); categories CRUD + starter set (FR-4.1/4.4); settings cadence UI. 69 backend + 5
  frontend tests. Deployed dev + prod via the pipeline on merge; owner smoke-tested dev,
  unauth/bad-token → 401 verified. `/code-review` adopted into `/wrap-slice` as an advisory
  step. No new ADR (design covered by architecture §2.4/§2.6). **Frontend is intentionally
  basic** (inline styles) — a visual pass is deferred; functionality-first for now.
- Prior: Slice 2 — GitHub OIDC deploy pipeline (ADR-011). Push to `main` runs the
  reusable `checks.yml` gate → auto-deploys `dev` → `prod` promotes on manual approval
  (GitHub Environment `prod`, owner = required reviewer). Zero long-lived AWS keys: a narrow
  `ledgerly-github-deploy` role only assumes the CDK bootstrap roles. New stacks:
  `Ledgerly-cicd` (OIDC provider + role, deployed once by hand) and `Ledgerly-prod`
  (deletion + termination protection on).
- Earlier: Slice 1 — walking skeleton deployed dev end-to-end (Cognito Hosted-UI/PKCE login →
  HTTP API JWT authorizer → `GET /settings` Lambda → DynamoDB round-trip, verified live);
  billing alarm; CI/CodeQL/Dependabot + AWS account guard (ADR-010) landed ahead of roadmap.
- Architecture (unchanged design): approved v1.1 → doc bumped to v1.2 (Slice-1 layout
  correction: AWS persistence lives in `backend/adapters/`, keeping `core/` AWS-free).
  ADR-001…011 Accepted.
- **Operational note:** every push to `main` now triggers a deploy run; pure-docs pushes are
  skipped via `deploy.yml` `paths-ignore`. `main` is not a protected branch (owner's call);
  the `prod` environment gate is the required-reviewer approval, not branch protection.
- **The roadmap lives in `docs/ledgerly-plan.md`** — slice order, per-slice scope,
  exit criteria, open decisions, and completion notes. Read the status board + current
  slice section at session start; update it when a slice wraps.
- Session rituals: `/start-slice` and `/wrap-slice` (project skills in `.claude/skills/`).

Refer to the architecture doc as you implement. If a decision needs to be made that isn't
covered, capture it as a new ADR in `ledgerly-adl.md` before coding it in.
