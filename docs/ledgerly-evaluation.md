# Ledgerly — Evaluation & Retrospective

**Status:** Living document — updated at each slice wrap and each release
**Last updated:** 2026-07-14

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
