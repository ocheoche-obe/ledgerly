# Ledgerly — Evaluation & Retrospective

**Status:** Living document — updated at each slice wrap and each release
**Last updated:** 2026-07-15

> Lifecycle stage 6. This is the hinge that turns the cycle: it measures what actually
> shipped against what we *said* we wanted, and its findings become the inputs to the next
> turn — new requirements, new ADRs, bug fixes, or parking-lot items. Without this stage,
> you have vibe coding with extra docs; with it, you have agentic engineering. Delete this
> note when real.

---

## How to use this document

- Evaluation happens at two altitudes:
  - **Per slice** (micro) — a short beat at `/wrap-slice`: did the slice meet its exit
    criteria, what did it actually cost, what surprised us? One entry below per slice.
  - **Per release / version** (macro) — a fuller retrospective when a version is "done":
    measure against the requirements doc's **Success Criteria** and the **NFRs**, then
    decide what the next cycle should carry.
- Every finding must **route somewhere**: a requirement, an ADR, a plan slice, or the
  parking lot. A finding with no destination is a finding that gets forgotten.

---

## 1. What we measure

Tie metrics back to the requirements doc so evaluation is objective, not vibes.

| Metric | Source (which FR/NFR/success criterion) | Target | How measured |
|---|---|---|---|
| {{e.g. end-to-end latency of primary flow}} | {{NFR-2.1}} | {{< N ms}} | {{how}} |
| {{monthly cost}} | {{NFR-1.1 ceiling}} | {{<= $N}} | {{billing/budget}} |
| {{correctness / quality of output}} | {{FR-X}} | {{...}} | {{...}} |
| {{reliability / error rate}} | {{NFR-3.1}} | {{...}} | {{...}} |

> If a success criterion has no metric, either add one or mark it explicitly qualitative.

---

## 2. Per-slice evaluation log

> One short entry per slice, added at `/wrap-slice`.

### Slice 1 — Walking skeleton (2026-07-14)
- **Met exit criteria?** Yes — all five. Login round-trip verified live in the browser;
  unauth → 401 (no-token + bad-token); billing alarm active; `pytest` 4/4; docs seeded.
- **Actual cost / resource use:** effectively $0 so far — all within free tier (DynamoDB
  on-demand, Lambda, HTTP API, Cognito) except CloudFront/S3 pennies. Dedicated account
  (ADR-010) means the account bill == Ledgerly spend, so the $5/$8 budget alarm is a true
  read. Well under the $10 ceiling (NFR-1.1).
- **What worked:** the CDK construct split synth'd and deployed clean first try (~4.7 min);
  runtime `config.json` pattern decoupled SPA build from stack outputs; the JWT authorizer
  rejected unauth requests before the Lambda (401s never reached compute).
- **What surprised us / didn't work:** (1) local Node v26 is jsii-untested by CDK — needed
  `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1` locally; CI pinned to Node 22. (2) The
  architecture's §5.2 layout self-contradicted ("no AWS in core" vs. `repo/` in `core/`) —
  resolved with a `backend/adapters/` seam (doc corrected to v1.2). (3) Security review
  caught dev-origin (`localhost`) leaking into the prod CORS + Cognito callback allowlists.
- **Findings routed to:**
  - Dedicated-account decision → **ADR-010** (Accepted).
  - `core/` vs AWS-imports contradiction → **architecture doc v1.2** correction.
  - Token-in-localStorage, CloudFront security headers/CSP, required MFA → **Slice 8**
    (hardening).
  - Deploy pipeline (OIDC, prod promotion) → **Slice 2** (was already its scope; narrowed).
  - Node/jsii + access-token-works gotchas → plan Slice 1 completion notes + memory.

### Slice 2 — CI/CD deploy pipeline + prod promotion (2026-07-15)
- **Met exit criteria?** Yes — all four, verified end-to-end on the live pipeline (run
  29471170254): push to `main` → `checks` gate → `deploy-dev` auto (`Ledgerly-dev`
  `UPDATE_COMPLETE`) → `deploy-prod` on manual approval (`Ledgerly-prod` `CREATE_COMPLETE`,
  termination protection on, unauth API → 401). No AWS secrets in GitHub — OIDC federation
  only. Docs current.
- **Actual cost / resource use:** still ~$0 MTD at slice start; the `prod` stack adds a
  second idle-serverless footprint (DynamoDB on-demand, Lambda, HTTP API, Cognito,
  CloudFront/S3 pennies) — expected cents/month, well under the $10 ceiling (NFR-1.1). The
  OIDC provider + role are free.
- **What worked:** the CDK bootstrap-role delegation (ADR-011) kept the internet-reachable
  identity narrow and the role policy trivial; the reusable `checks.yml` gave one test gate
  for both PRs and deploys; factoring build+deploy into a composite action made dev/prod
  identical while the job-level `environment:` set the OIDC subject and the approval gate.
- **What surprised us / didn't work:** (1) the moto adapter test passed locally but hit
  `NoRegionError` in CI — the adapter's region-less boto3 resource relies on the Lambda
  runtime's `AWS_REGION`, absent in CI; fixed by pinning region + dummy creds in the
  fixture. (2) Standing up the pipeline means **every push to `main` now deploys** — a
  pure-docs push would otherwise create a dangling prod-pending approval; added
  `paths-ignore` to `deploy.yml`. (3) The `prod` GitHub Environment's `protected_branches`
  policy would have blocked deploys because `main` isn't a protected branch — relaxed to
  `null` (the required-reviewer rule is the real gate).
- **Findings routed to:**
  - Deploy-role model → **ADR-011** (Accepted).
  - moto `NoRegionError` + "push to main deploys" gotchas → plan Slice 2 completion notes +
    memory.
  - Branch protection for `main` → **owner decision / parking lot** (prod gate works without
    it via required reviewer).
  - e2e browser tests → **Slice 6** (when the dashboard exists).

### Slice 3 — Categories, settings & budget-cycle engine (2026-07-19)
- **Met exit criteria?** Yes — all four. Cycle-engine unit tests cover both cadences +
  transitions (20 tests); docs current; categories + settings manageable in the deployed app
  (owner smoke-tested `dev`: login → starter set present → created a category → cadence
  monthly→two-week); deployed via the pipeline on merge of #21 (run 29675341086 — `deploy-dev`
  **and** `deploy-prod` both success; unauth/bad-token → 401 verified). Deploy was **post-merge
  by design** (Option A, preserving "no workstation deploys"); `cdk diff` was the pre-PR check.
- **Actual cost / resource use:** no new paid service — categories/settings ride the existing
  DynamoDB table + a second small API Lambda (`CategoriesFn`). Still ~$0 MTD; well under the
  $10 ceiling (NFR-1.1).
- **What worked:** the `core`/`adapters` seam paid off — the entire cycle engine is pure
  Python with zero AWS, so the dense date math (clamping, phase-lock, transitions) got 20
  fast unit tests with no mocking. Deriving cycles from a cadence *history* (append-only,
  `effectiveFrom`-keyed) made "never rewrite past cycles" fall out of the data model rather
  than needing special-case code.
- **What surprised us / didn't work:** (1) the first clamp implementation produced an invalid
  `start > end` window for dates before the earliest cadence's `effectiveFrom` — a unit test
  caught it; fix: the earliest cadence extends backward indefinitely (matters for back-dated
  imports in Slice 4). (2) `/code-review medium`, run as a trial, found two real correctness
  bugs that CI + tests + `/security-review` all passed clean over (a 500-vs-400 crash and a
  seed-ordering bug that could strand the owner with no categories) — with zero false
  positives. Strong enough signal that it's now an advisory step in `/wrap-slice`.
- **Findings routed to:**
  - Cycle-engine backward-extension + ULID/no-deps packaging → plan Slice 3 completion notes
    + memory.
  - `/code-review` value → **process change**: adopted into `/wrap-slice` (advisory, medium).
  - SPA stale access-token on silent renew (code-review #3) → **Slice 8** (existing token
    rework); not fixed this slice.

### Slice 5 — AI categorization pipeline + eval harness (2026-07-21, code-complete)
- **Met exit criteria?** Partial by design. Local gates green (164 backend + 13 frontend tests;
  ruff clean; `cdk synth` dev + prod). The three **live** criteria — a real import fully
  categorized within ~2 min (NFR-2.2), the DLQ failure path, and the **per-model accuracy
  baseline** — verify **post-merge on the pipeline** (Option A, no workstation deploy), and the
  baseline additionally needs the owner's labeled transaction sample. Held open until then.
- **Actual cost / resource use:** first paid-per-use AI service (Bedrock). MTD spend was **$0.01**
  at slice start; expected steady-state <$1/mo for categorization (ADR-008: ~10–15 batched calls
  on ~500 txns/mo). SQS/DLQ/Lambda ride the free tier. Ceiling (NFR-1.1) unthreatened — the eval
  A/B is the only near-term spend and is a handful of calls.
- **What worked:** the `Categorizer` interface (ADR-008) made the model a genuine config seam —
  the eval harness runs the *same* `decide_llm` production uses against both Opus 4.8 and Sonnet 5
  with zero code change. Keeping the decision matrix + prompt/parse contract pure meant the whole
  §3.2 logic (threshold, validity, GSI mapping) and the harness got fast unit tests with a fake
  model — no Bedrock in CI. The async pipeline's shape matched the pre-existing diagram exactly,
  so no re-render (same as Slice 4's ingest flow) — evidence the upfront architecture held.
- **What surprised us / didn't work:** (1) **Opus 4.8 (and Sonnet 5) are INFERENCE_PROFILE-only
  on Bedrock** — a bare `invoke_model` on the foundation-model id fails; the runtime id must be
  the inference-profile `us.anthropic.claude-opus-4-8`, and the IAM grant needs both the profile
  ARN and the cross-region foundation-model ARN. Caught by a live `list-foundation-models` check
  *before* deploy, not by a failed deploy. (2) The zero-runtime-deps posture forced a good call:
  Bedrock via **boto3 `invoke_model`** (native Anthropic body + forced-tool output) rather than
  the `anthropic` SDK — no layer, consistent with the hand-rolled-ULID reasoning.
- **Findings routed to:**
  - INFERENCE_PROFILE-only + boto3-not-SDK → **ADR-008 implementation notes** + plan Slice 5
    completion notes + memory (a live-cloud constraint future sessions need).
  - Model A/B (Opus 4.8 vs Sonnet 5) → **eval harness this slice** (turns the ADR-008 "measured
    downgrade" into a runnable A/B); result may seed a superseding ADR-008 note.
  - `/code-review` finding: rule-hit path doesn't re-validate the rule's category → **backlog B-4**
    → Slice 7 (rule creation); not triggerable now (rules table empty this slice).

---

## 3. Release / version retrospective

> Fuller pass when a version is done. Repeat this section per version (v1, v1.1, v2…).

### Version {{v1}} — {{date}}

**Scorecard against success criteria**

| Success criterion (from requirements §7) | Result | Notes |
|---|---|---|
| {{...}} | {{met / partial / missed}} | {{...}} |

**NFR scorecard**

| NFR | Target | Actual | Verdict |
|---|---|---|---|
| {{NFR-1.1 cost}} | {{$N}} | {{$actual}} | {{...}} |

**What worked well**
- {{...}}

**What didn't / what hurt**
- {{...}}

**What we learned** (especially where reality contradicted the docs — link the doc
correction or new ADR)
- {{...}}

**Decisions for the next cycle** — each routed:
- {{finding}} → {{new requirement / ADR-00X / plan slice / parking lot}}

---

## 4. Feedback loop — closing the cycle

The lifecycle is Requirements → Architecture → Implementation → Testing → Deployment →
**Evaluation → (back to Requirements)**. When a version's retrospective is complete:

1. Promote the accepted findings into `ledgerly-requirements.md` (new/changed FR/NFR)
   or into new ADRs in `ledgerly-adl.md`.
2. Re-slice the next version's work in `ledgerly-plan.md`.
3. Bump the plan's status board and CLAUDE.md phase marker to the new cycle.

---

## Change log

| Date | Change |
|---|---|
| 2026-07-12 | Initial evaluation scaffold |
| 2026-07-14 | Slice 1 per-slice beat added (walking skeleton — all exit criteria met) |
| 2026-07-15 | Slice 2 per-slice beat added (CI/CD deploy pipeline + prod promotion — all exit criteria met) |
| 2026-07-17 | Slice 3 per-slice beat added (categories, settings & cycle engine — code-complete at PR; deploy/smoke-test post-merge via pipeline). `/code-review` adopted into `/wrap-slice` |
| 2026-07-19 | Slice 3 beat finalized — deployed dev + prod on merge, all exit criteria met (owner smoke-test + unauth 401 verified) |
| 2026-07-21 | Slice 5 per-slice beat added (AI categorization pipeline + eval harness — code-complete at PR; live criteria + accuracy baseline post-merge via pipeline). Key finding: Bedrock Opus 4.8/Sonnet 5 are INFERENCE_PROFILE-only |
