# Ledgerly — Implementation Plan & Roadmap

**Status:** Living document — the authoritative "what order, what's done, what's next"
**Version:** 0.6
**Created:** 2026-07-12

---

## How to use this document

- **You (the owner):** the [Status board](#status-board) answers "where are we?"; the
  current slice's detail section answers "what are we doing and what do I need to decide?".
  Items marked ⚠ are decisions that will be brought to you *before* they're hit.
- **Claude:** read this at `/start-slice` (status board + current slice detail); update it
  at `/wrap-slice` (flip status, fill completion notes, confirm the next slice still holds).
  A slice is not done until this doc says so.

### Division of authority (no dual sources of truth)

Each doc owns one of the six questions:

| Document | Question | Owns |
|---|---|---|
| `ledgerly-requirements.md` | **Who / What** | users & personas; functional/non-functional requirements |
| `ledgerly-architecture.md` | **How / Where** | system design, data model, contracts, deployment target |
| `ledgerly-adl.md` | **Why** | every significant decision, as ADRs |
| **This document** | **When** | slice sequence & order, scope, status, completion notes |
| `ledgerly-evaluation.md` | — | stage-6 metrics & retrospectives that feed the next cycle |
| `CLAUDE.md` | — | compact session-start context; its phase marker just *points here* |

If this doc contradicts the architecture doc on a design matter, the architecture doc wins
and this doc gets fixed (or the contradiction becomes an ADR).

### The delivery lifecycle (this doc drives it)

Work runs the six-stage cycle from `KICKOFF.md`: **Requirements → Architecture →
Implementation → Testing → Deployment → Evaluation → (loop)**. Stages 3–5 (implementation,
testing, deployment) happen *inside each vertical slice* — a slice isn't done until it's
built, tested, and deployed. Stage 6 (evaluation) happens as a short beat at `/wrap-slice`
and as a fuller retrospective per release, both recorded in `ledgerly-evaluation.md`,
whose findings loop back into new requirements, ADRs, or slices here.

### Status legend

✅ done · 🔨 in progress · ⬜ not started · ⚠ has open decisions

---

## Guiding principles

1. **Vertical slices.** Every slice lands deployed and verified end-to-end (real
   infra, not just unit tests). "Works on localhost" is not an exit criterion unless the
   slice is frontend-only.
2. **ADR before code.** A decision the architecture doc doesn't cover gets written into
   the ADL *before* the code that implements it.
3. **Docs current before done.** `/wrap-slice` blocks on this doc, the ADL, and (when
   reality contradicted it) the architecture doc being updated.
4. **Cost ceiling.** $10/month (NFR-1.1). Slices that add a new paid service start with a
   budget-posture check. The billing alarm ships in Slice 1, before anything else.
5. **Learning vehicle.** When live cloud behavior contradicts the docs, surface the
   contradiction and correct the doc with reasoning — never silently code around it.
6. **Close the loop.** Every slice ends with a short evaluation beat; every release ends with
   a retrospective in `ledgerly-evaluation.md`. Findings route to a requirement, an
   ADR, a slice, or the parking lot — never nowhere.
7. **Diagram as code.** Architecture diagrams are generated from
   `docs/render_architecture.py` — any slice that changes the system shape re-renders the
   diagram in the same commit.

---

## Status board

| Slice | Name | Reqs covered | Status | PR |
|---|---|---|---|---|
| P0 | Requirements | — | ✅ approved v1.0 (2026-07-13) | — |
| P1 | Architecture design + foundational ADRs | — | ✅ complete (architecture v1.1 + slice roadmap approved 2026-07-13) | — |
| 1 | Walking skeleton (auth → API → data → UI, deployed) | FR-1, NFR-1.2, NFR-4.x | ✅ deployed to dev (2026-07-14) | [#1](https://github.com/ocheoche-obe/ledgerly/pull/1) |
| 2 | CI/CD **deploy** pipeline + prod promotion (test/lint/SAST CI already landed in Slice 1) | NFR-5.1/5.2/5.3 | ✅ deployed (2026-07-15) | [#19](https://github.com/ocheoche-obe/ledgerly/pull/19) |
| 3 | Categories, settings & budget-cycle engine | FR-4.1/4.2/4.4 | ✅ deployed (2026-07-19) | [#21](https://github.com/ocheoche-obe/ledgerly/pull/21) |
| 4 | CSV import end-to-end | FR-2.1–2.5 | 🔨 | — |
| 5 | AI categorization pipeline + eval harness | FR-3.1–3.3, 3.5 | ⬜ ⚠ | — |
| 6 | Budgets & at-a-glance dashboard | FR-4.3/4.5, FR-5.1–5.4 | ⬜ | — |
| 7 | Review queue, corrections & transaction management | FR-3.4, FR-6.1–6.3 | ⬜ | — |
| 8 | v1 hardening + first real cycle | NFR-7.x, success criteria | ⬜ | — |

> Slicing rationale: Slice 1 is the **thinnest end-to-end proof** that the whole stack
> works deployed (the kit's rule) — thinner than the interview candidate ("CSV upload →
> visible in UI"), which is real functionality layered on infra that has to exist anyway.
> That candidate lands as Slice 4, and by then it rides on a proven skeleton and pipeline.

---

## Completed slices

### Phase 0 — Requirements ✅
Completed 2026-07-13. Opening interview run 2026-07-12 (all six questions answered; see
requirements §8 for resolved questions); `ledgerly-requirements.md` drafted, owner-reviewed,
and approved as **v1.0** with two amendments: two-week budget-cycle cadence option added
alongside the monthly default (FR-4.2), and investment/savings *contributions* confirmed
budgetable while investment tracking stays out of scope (§3). ADR-001 (AWS,
serverless-first) recorded during setup.

### Phase 1 — Architecture design ✅
Completed 2026-07-13. Architecture approved (owner review; one amendment — rendered
AWS-style diagram added as diagrams-as-code, `docs/render_architecture.py`). Outputs:
`ledgerly-architecture.md` v1.1 (WHERE §0.1, system design, access-pattern-first data
model with cycle-keyed budgets, sequence diagrams, cross-cutting concerns, CDK/IaC
structure), ADR-002…009 all Accepted (architecture committed at `a01f58a`), and the
slice roadmap below (slices 1–8, owner-approved 2026-07-13). Next: Slice 1 via
`/start-slice` in a fresh session.

---

## Implementation slices

> Slices are sized for one or two evening/weekend sessions (business constraint §6).
> Key refs for every slice: architecture doc §2 (data model), §3 (sequences), §5 (IaC).

### Slice 1 — Walking skeleton ✅ (deployed to dev 2026-07-14)

- **Goal:** prove the entire stack works end-to-end, deployed: the owner logs into the
  deployed SPA, it makes an authenticated API call, and data comes back from DynamoDB.
- **Scope in:** CDK app + `dev` stack (constructs: Auth, Data, Api, Web, Ops); Cognito
  user pool + one admin-created user; HTTP API + JWT authorizer; one API Lambda
  (`GET /settings` — creates/returns the PROFILE item, defaulting to monthly cadence);
  DynamoDB table + GSIs (full key schema from day one — it's cheap and avoids migration);
  minimal React SPA (login via hosted UI/PKCE, call `/settings`, render the result);
  S3+CloudFront hosting; **billing alarm ($5 actual / $8 forecast)**; repo layout per
  architecture §5.2.
- **Scope out:** CI/CD (Slice 2 — manual `cdk deploy` is acceptable *only* this slice);
  any real feature UI; custom domain.
- **⚠ Open decisions:** none — all covered by ADR-001…009 (+ ADR-010, account topology,
  recorded during setup).
- **Exit criteria:** ☑ owner logs in on the deployed dev URL and sees the settings
  round-trip (verified live in browser) ☑ unauthenticated API request → 401 (curl: no-token
  and bad-token both 401) ☑ billing alarm confirmed active (`ledgerly-dev-monthly`, $10,
  $5/$8 notifications) ☑ `pytest` runs (4 passing) ☑ docs current (CLAUDE.md conventions +
  components seeded).
- **Completion notes:**
  - **Deployed dev stack `Ledgerly-dev`** (account `816020558700`, us-east-1): DynamoDB
    single table + GSI1/GSI2 (PITR on); Cognito pool + Hosted-UI domain + PKCE client +
    seeded owner user; HTTP API + JWT authorizer + `GET /settings` Lambda (least-privilege,
    table-scoped); private S3 + CloudFront (OAC) serving the SPA + runtime `config.json`;
    AWS Budgets alarm. Site: `dbe60z416ty5t.cloudfront.net`.
  - **Layout decision:** kept `backend/core/` AWS-free (the doc's stronger principle) by
    putting the DynamoDB adapter in `backend/adapters/` rather than `core/repo/`.
    Architecture §5.2 corrected + bumped to v1.2 (no design change).
  - **ADR-010** added (dedicated AWS account per project) + the account guard
    (`.claude/check-aws-profile.sh`, SessionStart hook, `/start-slice` hard assertion,
    `app.py` account pin).
  - **Beyond roadmap (owner-requested):** CI (pytest/ruff/build/`cdk synth`), CodeQL SAST,
    Dependabot under `.github/`; ruff introduced as the Python linter. `/wrap-slice` now
    enforces `/security-review` as a blocking pre-commit gate.
  - **Security review:** fixed CORS + Cognito callback localhost leaking into prod, and
    pinned `aws-cdk@2` in CI. Deferred to Slice 8: SPA token storage (localStorage → XSS),
    CloudFront security headers/CSP, required MFA. Accepted: `grant_read_write_data` breadth
    (architecture §4.2 idiom, resource-scoped).
  - **Gotchas:** local Node is v26 (jsii-untested by CDK) → use
    `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1` locally; CI uses Node 22. SPA sends the
    Cognito **access token** — confirmed accepted by the HTTP API JWT authorizer.
  - **Deferred to Slice 2:** the deploy pipeline itself (OIDC → auto-deploy dev, prod
    promotion) and prod stack creation. The prod-hardening CORS/callback fixes take effect
    when prod first deploys.

### Slice 2 — CI/CD pipeline + test scaffolding ✅ (deployed 2026-07-15)

- **Goal:** no more workstation deploys — merge to `main` ships `dev` automatically;
  `prod` exists and promotes on manual approval (NFR-5.2).
- **Already landed in Slice 1 (owner-requested):** the *CI-check* half — `ci.yml`
  (backend `pytest`/`ruff`, frontend build/test, `cdk synth`), CodeQL SAST, Dependabot.
  Slice 2 is now the *deploy* half only.
- **Scope in:** GitHub Actions with OIDC federation into a deploy role (no long-lived AWS
  keys); extend the pipeline: on merge to `main`, `cdk diff` → deploy `dev`; manually-
  approved `prod` promotion job; `prod` stack created (deletion + termination protection
  on); test scaffolding to grow: moto-based adapter tests for `backend/adapters`, first
  `vitest` tests for frontend — at minimum a smoke test (render `App`, assert the login
  screen appears) so the frontend CI job stops passing on `--passWithNoTests`. This gap
  became real 2026-07-15: the Dependabot wave landed React 19 + TS 7 + Vite 8 + vitest 4
  on `main` verified only by typecheck/build, with zero runtime coverage. The first
  pipeline deploy of this slice doubles as the runtime verification of that toolchain
  (browser login round-trip against dev).
- **Scope out:** e2e browser tests (revisit when the dashboard exists).
- **⚠ Open decisions:** none. (ADR-011 recorded the deploy-role model at slice start.)
- **Exit criteria:** ☑ push to `main` deploys dev with tests gating (run 29471170254:
  `checks` → `deploy-dev` success → `Ledgerly-dev` `UPDATE_COMPLETE`) ☑ prod promotion job
  runs and deploys the skeleton (manual approval → `Ledgerly-prod` `CREATE_COMPLETE`,
  termination protection on, API 401s unauth) ☑ no AWS secrets stored in GitHub (OIDC only)
  ☑ docs current.
- **Completion notes:**
  - **ADR-011 — OIDC deploy federation.** New stage-less `Ledgerly-cicd` stack (deployed
    once by hand, like `cdk bootstrap`) holds a GitHub OIDC provider + a **narrow** deploy
    role (`ledgerly-github-deploy`): its only power is `sts:AssumeRole`/`sts:TagSession` on
    the `cdk-hnb659fds-*` bootstrap roles — broad rights stay in the CFN exec role, zero
    long-lived AWS keys in GitHub. Trust scoped to exactly two subjects
    (`ref:refs/heads/main`, `environment:prod`).
  - **Pipeline shape.** `deploy.yml` on push to `main`: reusable `checks.yml` gate →
    `deploy-dev` (auto) → `deploy-prod` (GitHub Environment `prod`, required reviewer =
    owner). Build+deploy factored into a composite action (`.github/actions/cdk-deploy`)
    shared by both stages; the SPA is built (`npm ci && npm run build`) before `cdk deploy`
    because the `WebConstruct` reads `frontend/dist` as a plain-directory asset.
  - **CI refactor.** The Slice-1 `ci.yml` jobs became reusable `checks.yml`
    (`workflow_call`); `ci.yml` now runs it on PRs, `deploy.yml` runs it before deploying —
    one source of truth for the test gate.
  - **Test scaffolding (closed the wave gap).** moto-based adapter tests for
    `backend/adapters/dynamo.py` (3) + a vitest `App` smoke test (login screen renders);
    dropped `--passWithNoTests`. This is the runtime coverage the React 19 / TS 7 / Vite 8 /
    vitest 4 Dependabot wave lacked.
  - **`prod` stack now exists** (`CREATE_COMPLETE`, deletion + termination protection on):
    site `dbsk8bv05ju9b.cloudfront.net`, API `moar0no8ed`. First prod deploy seeded the
    owner Cognito user (temp password emailed) — real prod login is a Slice 8 concern.
  - **Gotchas:** (1) moto adapter test hit `NoRegionError` in CI (no ambient AWS region;
    the Lambda runtime always sets `AWS_REGION`) → fixture pins region + dummy creds.
    (2) Now that the pipeline is live, **every push to `main` triggers a deploy run**; a
    `paths-ignore` (docs/`*.md`) was added to `deploy.yml` so pure-docs pushes don't spin up
    a deploy + a dangling prod-pending approval.
  - **Deferred:** e2e browser tests (revisit at the dashboard, Slice 6); adding branch
    protection to `main` (the prod environment's branch policy was relaxed to `null` because
    `main` is unprotected — owner's call whether to protect it) → parking lot / owner
    decision.

### Slice 3 — Categories, settings & budget-cycle engine ⬜

- **Goal:** the owner can manage categories and set the budget-cycle cadence; the cycle
  math that everything downstream keys on exists and is thoroughly unit-tested.
- **Scope in:** `core/cycles.py` — cycle-ID computation (`M#…`/`B#…`), window resolution,
  cadence-change-effective-next-cycle semantics (FR-4.2), with exhaustive unit tests
  (month boundaries, anchor math, cadence transitions); categories CRUD API + UI
  (create/rename/archive — archive stubs reassignment until Slice 7 wires transactions);
  starter category set on first run (FR-4.4); settings UI (cadence + anchor date).
- **Scope out:** budget amounts (Slice 6); transaction reassignment on archive (Slice 7
  completes FR-4.5).
- **⚠ Open decisions:** starter category list contents — proposed default brought to
  owner during the slice (low stakes, fully editable).
- **Exit criteria:** ☑ cycle engine unit tests cover both cadences + transitions (20 tests:
  month boundaries, biweekly anchor/phase-lock, monthly↔biweekly transitions) ☑ docs current
  ☑ categories + settings manageable in deployed app (owner smoke-test: login → starter set
  present → created a category → cadence monthly→two-week) ☑ deployed via pipeline.
- **Completion notes:** _Deployed to `dev` **and** `prod` via the pipeline on merge of #21
  (run 29675341086 — `deploy-dev` + `deploy-prod` both success), keeping "no workstation
  deploys" intact (Option A; a workstation `cdk deploy` was also blocked by the auto-mode
  classifier, which aligned with the convention). Owner smoke-tested `dev` in-browser; unauth
  + bad-token requests to `/categories` and `PATCH /settings` verified → 401. `cdk diff`
  reviewed pre-PR (new `CategoriesFn` + 4 routes + CORS POST/PATCH; all table-scoped
  least-privilege)._
  - **Cycle engine (`core/cycles.py`)** — the heart of the slice, pure/AWS-free. Cycle IDs
    (`M#…`/`B#…`) + windows derived from the settings `cadences[]` history; windows are
    **clamped** to each cadence's span so no cycle straddles a cadence change (the transition
    cycle is just shorter, natural ID preserved). `plan_cadence_change` sets `effectiveFrom`
    at a future boundary so a change never rewrites the current/past cycles (FR-4.2). The
    **earliest cadence extends backward indefinitely** so back-dated CSV imports (Slice 4)
    still map to a cycle — this was a real bug the tests caught (clamp produced start>end).
  - **Categories (`core/categories.py` + adapter)** — CRUD (create/rename/archive), starter
    set seeded once on first `GET /categories`. Archive only flips status this slice;
    reassignment (FR-4.5) is Slice 7.
  - **Implementation calls (no ADR needed — covered by architecture §2.4/§2.6):**
    (1) **Hand-rolled ULID** (`core/ids.py`, stdlib-only) rather than a package — the Lambda
    asset ships as a plain source tree with no `pip install` step, so adding a dep would need
    a layer/vendoring; keeps the zero-runtime-deps posture. (2) **One method-routed Lambda
    per resource** (`SettingsFn` handles GET+PATCH; `CategoriesFn` handles GET/POST/PATCH).
    (3) `GET /settings` now also returns the **live current cycle** (engine-derived) so the
    SPA needs no date math and the engine is exercised in the deployed app.
  - **Code review adopted into cadence.** Ran `/code-review medium` as a trial this slice; it
    found 2 real correctness bugs (non-object `cadence` → 500 not 400; starter-seed flag set
    before the batch write → a crash could strand the owner with no categories) + 2 minor
    (stale-token = the known Slice-8 item; settings panel pre-filling a *scheduled* cadence).
    Fixed 1/2/4; #3 deferred to Slice 8. Zero false positives at `medium`. Now an **advisory
    (non-blocking) step 3 in `/wrap-slice`**.
  - **Tests:** 69 backend (cycle engine 20, categories/ids 15, adapter + handler integration
    via moto) + 5 frontend (api client + smoke). ruff clean; `/security-review` no findings.

### Slice 4 — CSV import end-to-end ⬜ ⚠

- **Goal:** the interview's slice-1 candidate, on real rails: upload a bank CSV, see
  transactions land in the deployed app with an import report.
- **Scope in:** presigned-upload flow (`POST /imports` → S3 PUT); import Lambda: parse,
  normalize (date/amount/direction/merchant), file- and row-level idempotency
  (FILEHASH#/txnId conditional puts), raw record preserved (FR-2.4), import summary with
  added/duplicate/failed counts (FR-2.5); import status UI (poll `GET /imports/{id}`,
  NFR-2.2); basic transaction list view (date-range query); source abstraction seam per
  FR-2.3 (parser behind an interface keyed by bank format).
- **Scope out:** categorization (Slice 5 — everything lands `Uncategorized` this slice);
  filters/search (Slice 7).
- **⚠ Open decisions (resolved at slice start):** the owner provided **two overlapping
  Chase checking exports** (`Chase5980_Activity_*`; the second a month-to-date subset).
  Only one bank/format is in play, so one parser this slice. Two data-model decisions
  surfaced from the real exports and became ADRs before code: **ADR-012** (transaction
  natural key includes `balanceCents` — the real exports contain legitimately-distinct
  same-day/-amount/-merchant charges, e.g. 3× `MIRRA VR` at −$31.76 on 06/29, that the
  §2.4 key would have silently collapsed; balance is stable per posted txn so FR-2.2
  holds) and **ADR-013** (account identity is an owner-confirmed `accountLabel` at upload,
  pre-filled from the filename).
- **Exit criteria:** ☑ re-uploading the same file adds zero duplicates (FR-2.2 — file-hash
  short-circuit; proven by `test_importer.py`, to be re-verified live) ☑ overlapping
  exports dedupe (row-level natural-key conditional put; integration-tested with two
  overlapping fixtures) ☑ malformed rows counted, not fatal (FR-2.5) ☑ import report
  visible (poll `GET /imports/{id}`) ☑ docs current ☐ deployed via pipeline + owner
  smoke-test on `dev` _(pending merge — Option A, no workstation deploy)_.
- **Completion notes:** _Code-complete; deploy + live smoke-test via the pipeline on merge
  (Option A, as Slice 3). 124 backend tests (was 69) + 13 frontend (was 5); ruff clean;
  `cdk synth` green for dev + prod._
  - **CSV pipeline (pure core → adapters → Lambdas).** `core/csv_normalize.py` = a
    format-keyed parser registry (FR-2.3; one impl, Chase checking) that turns raw text
    into normalized txns + counted row errors and **never raises on a bad row** (FR-2.5);
    `core/accounts.py` (ADR-013 identity), `core/imports.py` (import record + statuses),
    `core/transactions.py` (txn item shape, all Uncategorized this slice). Adapters:
    `dynamo.py` grew file-hash/txn conditional puts + import R/W; new `s3.py` mints the
    presigned PUT + recovers `<sub>/<importId>` from the S3 event key (identity from the
    key, never client input). Lambdas: S3-triggered `importer`, `api_imports`
    (presign + polling), `api_transactions` (date-window list).
  - **Idempotency at three levels held end-to-end** (integration-tested): file
    (`FILEHASH#`), row (natural key incl. balance), and **S3 at-least-once redelivery** — a
    redelivered event for an already-terminal import is a no-op (guard added so counts don't
    recompute to all-duplicate); `claim_file` recognizes its own prior claim so a mid-crash
    replay resumes rather than false-flagging the file as a duplicate.
  - **New `IngestConstruct`** (upload bucket: private, SSE-S3, TLS-only, 30-day object
    expiry since raw is preserved in DynamoDB per FR-2.4, CORS scoped to the SPA origin[s]
    for the browser PUT; import Lambda: 2-min timeout, table + bucket-read least-privilege;
    S3→Lambda notification on `.csv`). `ApiConstruct` gained the imports/transactions
    Lambdas (+ `s3:PutObject` on the bucket so presigned URLs work) and their routes.
    **No SQS yet** (Slice 5). The architecture **diagram already depicted this exact ingest
    flow** (S3 CSV uploads → import_handler → DynamoDB, 30-day expiry), so no system-shape
    change to re-render.
  - **Frontend:** `ImportPanel` (file pick → account label pre-filled from filename &
    editable → presign → PUT to S3 → poll the report; recent-imports list) +
    `TransactionsPanel` (date-window table, signed amounts). `api.ts` typed client +
    `accountLabelFromFilename`/`formatCents` helpers (unit-tested).
  - **Docs:** ADR-012/013 added (index + bodies); architecture bumped to **v1.4** (§2.4 key
    formula + `IMPORT#.accountLabel`).

### Slice 5 — AI categorization pipeline + eval harness ⬜ ⚠

- **Goal:** imported transactions get categorized automatically with confidence, async,
  and accuracy is *measured*, not vibes (NFR-5.3).
- **Scope in:** SQS queue + DLQ + alarm (ADR-009); categorizer Lambda: merchant-rule
  lookup → Bedrock (Claude Opus 4.8) with structured output, batched (architecture
  §3.2); confidence threshold → `needsReview` flag + GSI2; failure path → Uncategorized,
  never lost (FR-3.5); Bedrock IAM grant scoped to the one model; **eval harness**: a
  labeled sample set of the owner's real (anonymized-enough) transactions + a script that
  reports accuracy per run — the gate for prompt/model changes and the measurement for
  success criterion 2; budget-posture check (first paid-per-use AI service — expected
  <$1/mo, ceiling unaffected).
- **Scope out:** review-queue UI (Slice 7); merchant-rule *creation* (Slice 7 — this
  slice only reads rules, so the table starts empty and everything goes to the LLM).
- **⚠ Open decisions:** confidence threshold default (proposal: 0.8, tuned against the
  eval set during the slice); prompt shape iterations recorded in the eval harness, not
  ad-hoc.
- **Exit criteria:** ☐ a real import ends fully categorized within ~2 min (NFR-2.2) ☐
  DLQ path verified (forced failure lands Uncategorized + alarm) ☐ eval harness reports
  a baseline accuracy number ☐ docs current (+ ADL note if threshold ≠ 0.8).
- **Completion notes:** _—_

### Slice 6 — Budgets & at-a-glance dashboard ⬜

- **Goal:** the product's reason to exist: budget vs. actual per category for any cycle,
  in one glance.
- **Scope in:** budget amounts per category per cycle (`PUT /cycles/{id}/budgets/{cat}`,
  FR-4.3) + editing UI; cycle summary endpoint (budgets + windowed transactions,
  aggregated — architecture §3.3); dashboard screen: per-category budget vs. actual,
  totals (in/out/remaining), drill-down to transactions (GSI1), past-cycle picker
  (FR-5.3); responsive layout verified on a phone (FR-5.4); NFR-2.1 (<2s) and NFR-7.1
  (no-scroll desktop glance) checked against the deployed app.
- **Scope out:** trends across cycles (parking lot).
- **⚠ Open decisions:** dashboard visual design — a proposed layout brought to owner
  early in the slice.
- **Exit criteria:** ☐ owner answers "where is my money going, am I over anywhere?" from
  one deployed screen ☐ works on phone browser ☐ past cycles viewable ☐ docs current.
- **Completion notes:** _—_

### Slice 7 — Review queue, corrections & transaction management ⬜

- **Goal:** close the human-in-the-loop learning circle: triage low-confidence items,
  correct anything, and have corrections teach the system (FR-3.4).
- **Scope in:** review queue UI (GSI2) with quick confirm-or-correct (FR-6.3);
  re-categorize from list + drill-down (FR-6.2) with optimistic UI (NFR-2.3); correction
  writes merchant rule (architecture §3.4) — categorizer starts getting rule hits;
  recent corrections as few-shot examples in the prompt; transaction filters/search
  (date, category, amount, text — FR-6.1); category archive completes FR-4.5
  (reassignment choice wired to real transactions).
- **Scope out:** nothing carried forward — this completes the FR-3/FR-6 surface.
- **⚠ Open decisions:** none expected.
- **Exit criteria:** ☐ correcting a transaction visibly improves the next import (rule
  hit) ☐ review queue triage feels fast (NFR-2.3) ☐ filters work ☐ archive requires
  reassignment choice ☐ docs current.
- **Completion notes:** _—_

### Slice 8 — v1 hardening + first real cycle ⬜

- **Goal:** cut over to real use and start the clock on the success criteria.
- **Scope in:** prod promotion of the full app; owner runs the first **real check-in
  ritual** on prod (import → triage → dashboard) with actual bank data; measure: ritual
  time (NFR-7.2 <15 min), categorization accuracy (criterion 2 baseline), billing
  actuals vs. ceiling (criterion 4); fix the sharp edges that real use surfaces; seed
  `ledgerly-evaluation.md` with the v1 measurement plan + first data points.
- **Security hardening carried from Slice 1's review (financial-data posture):**
  - SPA auth-token storage — move off `localStorage` (XSS-exfiltration risk for the 30-day
    refresh token); evaluate in-memory + silent renew or a token-handler pattern. May
    warrant an ADR when the approach is chosen.
  - CloudFront **security response headers** — add a `ResponseHeadersPolicy` (CSP tuned to
    the Cognito domain + API origin, HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options`).
  - **Require MFA** on the Cognito pool (currently `OPTIONAL`; TOTP already enabled).
- **Scope out:** anything that looks like a new feature → parking lot.
- **⚠ Open decisions:** whether a custom domain is wanted for daily use.
- **Exit criteria:** ☐ owner completes a real cycle ritual on prod ☐ evaluation doc
  live with first metrics ☐ retrospective beat done ☐ docs + CLAUDE.md phase marker
  flipped to "v1 in real use — evaluation running".
- **Completion notes:** _—_

---

## Post-MVP parking lot

> Everything deferred lives here and *nowhere else*, so the slice sections stay honest.
> (Mirrors requirements §3 "Deferred"; this list carries the delivery-order notes.)

- **Plaid live bank connection** — top deferred item; sandbox first. Trigger: v1 monthly
  ritual proven (success criterion 1) and owner appetite to revise the cost ceiling
  (ADR required per NFR-1.1). Architecture seam ready: second ingest source behind FR-2.3.
- **Month-over-month trends** — cheapest promotion; mostly queries + dashboard work once
  months of data exist. Trigger: 2–3 months of real data in the system. Note: first new
  event subscriber → introduces EventBridge per ADR-009's recorded trigger.
- **Recurring/subscription detection** — needs several months of data to be meaningful.
- **Alerts/notifications** — pulls in email/push infrastructure; do after budgets feel
  trustworthy.
- **Savings goals** — after trends.
- **Ask-my-finances chat** — richest AI-agent learning surface; do when the data layer is
  stable and worth conversing with.

---

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-12 | Initial roadmap scaffold: P0/P1 phases, slice-1 candidate, parking lot from interview |
| 0.2 | 2026-07-13 | P0 complete: requirements approved v1.0 (two amendments); P1 marked next |
| 0.3 | 2026-07-13 | P1 architecture approved (v1.1, ADR-002…009); v1 sliced into slices 1–8 (walking skeleton first); diagram-as-code principle added |
| 0.4 | 2026-07-13 | Slice roadmap owner-approved; P1 marked complete. Diagram-as-code skill removed from the plan — it's a portable side deliverable for the project-starter kit, not Ledgerly scope |
| 0.5 | 2026-07-14 | Slice 1 ✅ deployed to dev (walking skeleton, all exit criteria met). ADR-010 (dedicated account) added. CI/CodeQL/Dependabot + AWS account guard landed ahead of roadmap; Slice 2 narrowed to the deploy pipeline. Slice-1 security review's deferred items folded into Slice 8 |
| 0.6 | 2026-07-15 | Slice 2 ✅ deployed (OIDC deploy pipeline + prod promotion). ADR-011 added. `Ledgerly-cicd` + `Ledgerly-prod` stacks created; reusable `checks.yml`; moto + vitest tests close the Dependabot-wave coverage gap. Both exit criteria verified end-to-end (dev auto-deploy, prod on manual approval) |
| 0.7 | 2026-07-17 | Slice 3 🔨 code-complete, PR open (categories CRUD + settings cadence UI + `core/cycles.py` engine, 69 backend/5 frontend tests). Deploy via pipeline on merge (Option A — no workstation deploy), so deploy/smoke-test exit criteria stay open until then. `/code-review medium` trialled and adopted as advisory step 3 of `/wrap-slice`. No new ADR (design covered by architecture §2.4/§2.6) |
| 0.8 | 2026-07-19 | Slice 3 ✅ deployed (dev + prod via pipeline on merge of #21). All exit criteria met: owner smoke-tested dev, unauth/bad-token → 401 verified. Next: Slice 4 — CSV import (needs owner's sample bank CSVs at start) |
| 0.9 | 2026-07-19 | Slice 4 🔨 code-complete: CSV import end-to-end (presigned upload → S3 → import Lambda → transactions), FR-2.1–2.5. ADR-012 (natural key incl. balance) + ADR-013 (account label at upload) recorded from the owner's real Chase exports; architecture → v1.4. New `IngestConstruct`; 124 backend + 13 frontend tests. Deploy + live smoke-test via pipeline on merge (Option A) — those exit criteria stay open until then |
