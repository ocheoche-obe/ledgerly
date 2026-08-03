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
- **`docs/ledgerly-backlog.md`** — build-time observation inbox: papercuts, tech-debt,
  small enhancements noticed mid-slice, awaiting triage into a slice / the plan's parking
  lot / an ADR (not a second roadmap — items get promoted out).
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
  Claude Sonnet 4.6 via Amazon Bedrock with structured output (ADR-008 as amended). **Zero runtime
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
  (no runtime deps — the Lambda asset has no `pip` step). `csv_normalize.py`: format-keyed
  CSV parser registry (FR-2.3; Chase-checking impl) → normalized txns + counted row errors,
  never raises on a bad row (FR-2.5); natural key `sha256(account·date·amountCents·rawDesc·
  balanceCents)[:16]` (ADR-012). `accounts.py`: account label→id (ADR-013). `imports.py`:
  import record + statuses. `transactions.py`: txn item shape + `auto` status + GSI1/GSI2 key
  helpers (categorizer writes these). `categorize/`: **Categorizer interface** (swappable model
  seam, ADR-008) + §3.2 decision matrix (`decide_llm`: threshold → auto vs kept-guess-with-review;
  null/invalid id → uncategorized, nothing mis-filed) + prompt/forced-tool contract.
  `merchant_rules.py`: `RULE#<merchant>` read seam (FR-3.4; read-only until Slice 7).
- **`backend/adapters/`** — AWS-facing persistence (boto3). `dynamo.py`:
  `get_or_create_settings` (AP #1), `update_cadence` (FR-4.2), `list/create/update_category`
  (AP #2/#3), Slice-4: `create/get/list_imports` + `set_import_status` (AP 11),
  `claim_file` (AP 12, file idempotency — recognizes its own replay), `put_transaction`
  (AP 7, row idempotency), `query_transactions` (AP 6), plus Slice-5: `list_category_choices`,
  `get_rule` (AP 13), `get_transaction`, `apply_categorization` (AP 10, correction-preserving
  update + GSI1/GSI2 maintenance). `s3.py`: presigned PUT URL + `<sub>/<importId>` key
  round-trip. `bedrock.py`: `BedrockCategorizer` via **boto3 `invoke_model`** (not the
  `anthropic` SDK — zero runtime deps), inference-profile `us.anthropic.claude-sonnet-4-6`
  (INFERENCE_PROFILE-only; Opus 4.8 was the original choice but this account cannot invoke it —
  ADR-008 amendment 2026-08-03), forced-tool structured output. `sqs.py`: best-effort
  categorization enqueue (a failed enqueue never fails a persisted import, FR-3.5).
- **`backend/functions/`** — thin handlers, identity from verified JWT claims only (FR-1.3):
  `api_settings` (`GET`/`PATCH /settings`, live cycle), `api_categories` (`GET`/`POST
  /categories` + `PATCH /categories/{id}`), `api_imports` (`POST /imports` presign +
  `GET /imports[/{id}]` polling), `api_transactions` (`GET /transactions?from&to`), the
  **S3-triggered `importer`** (parse → file/row idempotent puts → import summary → enqueue added
  rows; no-op on redelivered terminal imports), and the **SQS-triggered `categorizer`**
  (rule-first → batched Bedrock → correction-preserving updates; partial-batch-failure → DLQ).
  `backend/eval/` (not a Lambda): the label/score accuracy harness A/Bing Sonnet 4.6 vs Haiku 4.5.
- **`infra/` (CDK, Python)** — `LedgerlyStack` (per-stage `Ledgerly-dev`/`Ledgerly-prod`) =
  constructs: `Data` (DynamoDB single table + GSI1/GSI2, PITR), `Auth` (Cognito pool +
  Hosted-UI/PKCE client + owner user), `Ingest` (private SSE-S3 upload bucket: TLS-only,
  30-day object expiry, CORS scoped to the SPA origin[s]; import Lambda; S3→Lambda
  notification on `.csv`), `Api` (HTTP API + JWT authorizer + settings/categories/imports/
  transactions Lambdas via a shared `_api_lambda` helper, each table-scoped least-privilege;
  imports Lambda also gets `s3:PutObject` on the bucket; importer also gets `sqs:SendMessage`
  on the categorization queue), `Categorization` (SQS queue + DLQ maxReceive 3 + DLQ-depth
  alarm + categorizer Lambda + Bedrock `InvokeModel` IAM scoped to the one model's profile +
  foundation-model ARNs, ADR-008/009), `Web` (private S3 + CloudFront + runtime `config.json`),
  `Ops` (AWS Budgets billing alarm). Separately, `LedgerlyCicdStack` (`Ledgerly-cicd`,
  account-global, deployed once) =
  `Cicd` construct: GitHub OIDC provider + narrow `ledgerly-github-deploy` role (ADR-011).
- **`.github/` (CI/CD)** — `checks.yml` (reusable test/lint/synth gate) called by `ci.yml`
  (PRs) and `deploy.yml` (push to `main` → deploy `dev`, then manual-approved `prod` via the
  `cdk-deploy` composite action); `codeql.yml` (SAST); `dependabot.yml`.
- **`frontend/` (React+Vite+TS)** — Hosted-UI PKCE login, fetches runtime `/config.json`.
  `api.ts` = typed client (bearer token on every call) + `accountLabelFromFilename`/
  `formatCents` helpers. `SettingsPanel` = cadence + current cycle; `CategoriesPanel` =
  category CRUD; `ImportPanel` = CSV upload (presign → PUT to S3 → poll import report) +
  recent imports; `TransactionsPanel` = date-window transaction table with a **Category** column that reflects
  the async pipeline (reads Uncategorized until the categorizer runs, then the category name +
  a "review" tag on low confidence, Slice 5); `styles.ts` = shared inline styles.

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
- **Deployed ≠ working (learned the hard way, Slice 5):** the pipeline deploys code; it does not
  *exercise* it. A slice whose exit criteria include live behaviour is **not done until someone
  runs those criteria against the deployed stack** — a green `deploy.yml` is not evidence the
  feature works. Slice 5 sat "deployed" for 12 days while every categorizer invocation failed on
  an ungranted Bedrock model agreement, because nobody ran the ☐ items. Option A ("deploy via the
  pipeline on merge") is a *shipping* strategy, not a *verification* strategy.
- **Who merges (owner decision, 2026-08-02):** `Bash(gh pr merge:*)` is allowlisted in
  `.claude/settings.local.json`, so Claude *can* merge — but the permission is a capability, not
  a licence. The split is by **kind of PR**, and it is a judgement call Claude makes, since no
  permission rule can distinguish them:
  - **Slice PRs — owner merges.** Anything from `/wrap-slice`, i.e. feature work with an exit-
    criteria checklist. Claude opens the PR, gets CI green, and stops. Reviewing the slice *is*
    the owner's checkpoint on the build; auto-merging would erase it.
  - **Cleanup PRs — Claude may merge once CI is green.** Dependency waves, CI/lint repairs,
    infra hygiene, docs/backlog entries. No new product behaviour, and the diff is mechanical
    or self-evident from the PR body.
  - When it isn't obvious which bucket a PR is in, ask. Anything that changes deploy behaviour,
    IAM, or data handling is a slice PR regardless of how small the diff looks.

## Cost constraints

- **$10/month effective hard ceiling** (NFR-1.1) — single-user personal app; serverless
  keeps idle cost near zero. Plaid production would be a deliberate ADR-recorded revision.
- Guards in place: **AWS Budgets alarm live** ($5 actual / $8 forecast) as of Slice 1
  (NFR-1.2); the dedicated account (ADR-010) makes the account bill == Ledgerly spend.
  Bedrock spend rides the same AWS bill, so the alarm covers LLM cost too (ADR-008).
  Expected steady state ≈ $2–4/month total.

## Current build phase

**Slice 5 — AI categorization pipeline + eval harness: ✅ COMPLETE (2026-08-03). Next: Slice 6 —
budgets & at-a-glance dashboard, starting with [B-7] (see below). Start it with `/start-slice`.**

Slice 5 shipped 2026-07-21 (#25) and was **broken on arrival for 12 days**: every categorizer
invocation failed with `AccessDeniedException` on Opus 4.8. Root cause was **account-tier
eligibility, not a missing model agreement** — the owner accepted the agreement (CloudTrail-
confirmed) and invocation was *still* denied, as was Sonnet 5 as a control. Invocable on this
account: **Haiku 4.5 · Sonnet 4.5 · Sonnet 4.6**; denied: **Opus 4.7 · Opus 4.8 · Sonnet 5**.
Categorizer switched to **Claude Sonnet 4.6** (#41, ADR-008 amendment) — interim; revisit →
Sonnet 5 if the owner's frontier-tier request is granted. **Note for future Bedrock debugging:
all four `get-foundation-model-availability` fields read AVAILABLE/AUTHORIZED for a model that
cannot be called — only invocation is a reliable signal.**

**Verified live 2026-08-03:** redriving the DLQ (`sqs start-message-move-task`) returned the
original failed message; the categorizer wrote **8/8 in ~24s** (NFR-2.2 budget is ~2 min) at
**8/8 accuracy**, with calibrated confidence — 0.99 on unambiguous merchants, 0.85 Amazon, 0.80
Walgreens. ⚠ Walgreens scored *exactly* 0.80 and auto-filed, so the threshold is **inclusive
(`>=`)** — confirm that's intended when Slice 7 sizes the review queue. Earlier, the DLQ path was
verified by an unforced real failure (3 retries 360s apart → DLQ → alarm, everything left
Uncategorized): FR-3.5's "un-filed, never mis-filed" promise proven on real infrastructure.

**Carry into Slice 6:** **[B-7] is the first task, owner-approved** — build
`POST /transactions/recategorize` (a date-window re-enqueue) and run it over the 153 real
transactions stranded uncategorized since Slice 4 (the importer only enqueues newly-added rows;
ADR-012 idempotency means a re-import adds 0). Do it *before* the dashboard, or the product's core
screen demos at $0 across every category. Chosen as an endpoint rather than a one-off script
because Slice 7's review queue needs the same capability. Eval baseline stays deferred (**[B-8]**);
the 0.8 threshold remains unvalidated beyond the 8-row smoke set. The only categorized data in dev
today is those 8 synthetic `slice5-smoke-checking` rows, kept deliberately so Slice 6 has
something realistic to build against until B-7 lands.

- Last completed (code): Slice 5 — `core/categorize/` (Categorizer interface + §3.2 decision
  matrix + prompt/forced-tool contract), `core/merchant_rules.py` (RULE# read seam),
  `adapters/bedrock.py` (BedrockCategorizer via **boto3 `invoke_model`**, not the `anthropic`
  SDK — zero runtime deps) + `adapters/sqs.py` (best-effort enqueue) + `dynamo.py`
  categorization methods (`list_category_choices`, `get_rule`, `apply_categorization` —
  correction-preserving + GSI1/GSI2 maintenance), `functions/categorizer` (SQS-triggered,
  rule-first → batched Bedrock, partial-batch-failure → DLQ), `CategorizationConstruct`
  (SQS+DLQ+alarm+Bedrock IAM), and `backend/eval/` (label/score harness, now A/Bing Sonnet 4.6
  vs Haiku 4.5). Confidence threshold **0.8** (owner-approved). **Bedrock note:** the models are
  INFERENCE_PROFILE-only → model id `us.anthropic.claude-sonnet-4-6`; IAM grant covers profile +
  foundation-model ARNs (ADR-008 impl notes). No new ADR (design covered by ADR-008/009 +
  architecture §3.2). No diagram re-render — the async pipeline was already depicted.
- Prior: Slice 4 — presigned CSV upload → S3 → import Lambda → transactions,
  FR-2.1–2.5. New `IngestConstruct` (upload bucket + S3-triggered importer);
  `core/csv_normalize.py` format-keyed parser (Chase checking); three-level idempotency
  (file hash / row natural key / S3 redelivery). Two ADRs from the owner's real Chase
  exports: **ADR-012** (natural key includes `balanceCents` so legit same-day/-amount/
  -merchant charges aren't collapsed) + **ADR-013** (owner-confirmed account label at upload).
  Architecture → v1.4. 124 backend + 13 frontend tests; ruff clean. Everything lands
  **Uncategorized** (categorization is Slice 5). **New process:** `ledgerly-backlog.md` — a
  build-time observation inbox — introduced this slice (first entry B-1: the import Account
  field is free text with no registry → a first-class Accounts entity + dropdown picker,
  since `accountId` is a dedupe-key component). **Frontend stays intentionally basic** (inline
  styles) — visual pass deferred (backlog B-3).
- Last completed: Slice 3 — `core/cycles.py` budget-cycle engine (cycle IDs/windows from the
  cadence history, clamped so no cycle straddles a change; change-effective-next-cycle,
  FR-4.2); categories CRUD + starter set (FR-4.1/4.4); settings cadence UI. 69 backend + 5
  frontend tests. Deployed dev + prod via the pipeline on merge (PR #21); owner smoke-tested
  dev, unauth/bad-token → 401 verified. `/code-review` adopted into `/wrap-slice` as an
  advisory step. No new ADR (design covered by architecture §2.4/§2.6).
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
