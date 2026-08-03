# Ledgerly — Build-Time Backlog

**Status:** Living document — append as things are noticed; triage as slices are planned
**Version:** 0.1
**Created:** 2026-07-21

---

## What this is

A running list of **observations noticed while building** — papercuts, small enhancements,
tech-debt, data-integrity risks, UX rough edges — that are **real but don't justify
interrupting the current slice**. It exists so those items land *somewhere* the moment
they're spotted, instead of being lost or forced into a slice that isn't about them (which
would erode the plan doc's honesty about what each slice is for).

### How it relates to the other docs (no dual source of truth)

This is deliberately **not** a second roadmap. Each entry is unscheduled and awaiting triage;
its job is to eventually be **promoted out of here** into exactly one home:

| If the item is… | It belongs in… |
|---|---|
| a **deferred post-MVP feature** tied to requirements §3 (Plaid, trends, chat, …) | the plan's **Post-MVP parking lot** (with a delivery-order trigger) |
| **scoped work for an upcoming slice** | the relevant **slice section** in `ledgerly-plan.md` |
| a **design decision** that needs recording | a new **ADR** in `ledgerly-adl.md` |
| a **metric / retrospective finding** | `ledgerly-evaluation.md` |
| **not worth doing** | dropped (strike it, note why) |

So: the **plan** owns *when* (scheduled slices + the post-MVP parking lot); this backlog is
the **inbox** in front of that — loose build-time notes before they're triaged into a home.
When an item is promoted or dropped, mark it Done/Dropped here with a pointer, don't delete it
(the trail is the value).

### Status legend

🆕 new · 🔎 triaged (home decided, not yet done) · ✅ promoted/done · ✖ dropped

---

## Backlog

| ID | Item | Noticed | Type | Status | Likely home |
|---|---|---|---|---|---|
| B-1 | Account field is free-text (a key component you can mistype) | Slice 4 | UX / data-integrity | 🆕 | new small slice (Accounts entity + picker) |
| B-2 | Transaction list has no pagination + a fixed default window | Slice 4 | tech-debt / UX | 🔎 | Slice 7 (filters/search) |
| B-3 | Frontend is intentionally basic (inline styles) — visual pass deferred | Slice 1 | UX / polish | 🔎 | later (dedicated polish pass) |
| B-4 | Categorizer rule-hit path doesn't validate the rule's category is still active | Slice 5 | correctness / data-integrity | 🔎 | Slice 7 (rule creation) |
| B-5 | Dependabot's two **pip** groups don't actually group — one PR per package | 2026-08 wave | process / noise | 🆕 | verify at the next monthly run |
| B-6 | `infra/requirements.txt` has the unbounded-minor exposure just fixed in `backend/` | 2026-08 wave | tech-debt / reproducibility | 🆕 | next infra-touching slice |
| B-7 | No backfill path — the 153 already-imported transactions can never be categorized | Slice 5 live test | correctness / UX | 🆕 | **Slice 6 blocker** (dashboard would read all-Uncategorized) |
| B-8 | Eval baseline deferred by owner until the app is more fully built | Slice 5 live test | process / quality | 🔎 | revisit after Slice 7 |

---

### B-1 — Account identity is a free-text field the owner can mistype 🆕

**Noticed:** Slice 4 smoke test (owner). **Type:** UX / data-integrity.

The import screen's **Account** field is free text, pre-filled from the filename
(`Chase5980_Activity…` → `Chase …5980`) and normalized server-side to an `accountId`
(`chase-5980`) that is **part of the transaction dedupe key** (ADR-012). There is no place in
the app to define/manage accounts — it's just this one editable box.

**Why it matters:** because `accountId` is a key component, editing the field *inconsistently*
silently corrupts dedupe. Editing the descriptive part is safe (`Chase …5980` / `Chase 5980` /
`Chase Checking 5980` all normalize to `chase-5980`), but **dropping the account number**
(→ `Chase` → `chase`) creates a *different* account: prior transactions no longer dedupe (they
re-import as new) and history splits across two `accountId`s. ADR-013 anticipated exactly this
("owner responsibility… promoting `accountLabel` to a first-class Account entity with a picker
is a natural later slice").

**Proposed fix:** a first-class **Accounts** entity (CRUD like categories) + a **dropdown
picker** on import, so the owner can only *select* a canonical account, never mistype the key.
Removes the footgun entirely and is multi-account-ready. Roughly one small slice (mirrors the
categories CRUD already built). **Not urgent:** single user, one account, and the filename
pre-fill keeps it consistent in normal (unedited) use.

**Refs:** ADR-013, ADR-012; `frontend/src/ImportPanel.tsx`; `backend/core/accounts.py`.

---

### B-2 — Transaction list: no pagination, fixed default window 🔎

**Noticed:** Slice 4 (code review). **Type:** tech-debt / UX. **Likely home:** Slice 7.

`GET /transactions` returns a single DynamoDB page (`Limit=500`) over a default 90-day window
(`_DEFAULT_WINDOW_DAYS`). Two consequences: (1) a window with >500 transactions **silently
truncates** (list + count both under-report); (2) a **back-dated import older than the default
window** doesn't appear in the basic list even though it was added. Neither bites at Slice-4
sizes (a month ≈ a few hundred rows, and recent imports fall inside 90 days), but both should
be closed when **filters/search + a date-range picker land in Slice 7** — add pagination
(follow `LastEvaluatedKey`) and let the owner choose the window.

**Refs:** `backend/adapters/dynamo.py` (`query_transactions`);
`backend/functions/api_transactions/handler.py`; `frontend/src/TransactionsPanel.tsx`.

---

### B-3 — Frontend is intentionally basic; visual/design pass deferred 🔎

**Noticed:** Slice 1 (recorded across slices). **Type:** UX / polish. **Likely home:** a
dedicated polish pass (candidate: alongside Slice 8 hardening, or its own slice).

The SPA uses hand-rolled inline styles (`styles.ts`), no design system — a deliberate
functionality-first choice while the UI is small. A cohesive visual pass (layout, spacing,
responsive dashboard, empty/loading states, accessibility) is worth doing once the core
product surface (import → categorize → dashboard → review) exists, so the design is done
against the real thing rather than re-done each slice.

**Refs:** `frontend/src/styles.ts` and all panels.

---

### B-4 — Categorizer rule-hit path doesn't re-validate the rule's category 🔎

**Noticed:** Slice 5 (code review). **Type:** correctness / data-integrity. **Likely home:** Slice 7.

The categorizer's LLM path validates the returned `categoryId` against the owner's *active*
categories (`decide_llm` → unknown/archived id degrades to `uncategorized`). The **merchant-rule
path** (`decide_rule_hit`) does not — it assigns the rule's stored `categoryId` verbatim. A rule
that points at a since-archived category would therefore auto-assign an archived bucket (and set
its GSI1 key), which the LLM path would have refused.

**Why it's not a Slice-5 bug:** merchant-rule *creation* is Slice 7 — this slice only *reads*
rules, and the table starts empty, so no rule can fire. The guard belongs with rule creation:
when Slice 7 wires corrections → rules, either validate the rule's category on write, or have the
categorizer drop a rule whose category is no longer active (mirroring the LLM validity check).

**Refs:** `backend/functions/categorizer/handler.py`; `backend/core/categorize/__init__.py`
(`decide_rule_hit` vs `decide_llm`); relates to FR-4.5 (archive/reassignment, Slice 7).

---

### B-5 — The two pip Dependabot groups aren't grouping 🆕

**Noticed:** 2026-08-01 wave (triage). **Type:** process / noise. **Likely home:** verify at the
next monthly run.

`dependabot.yml` defines `backend-minor-patch` and `infra-minor-patch`, both keyed on
`update-types: [minor, patch]`. Neither fired: the wave produced **one PR per package** —
#26 (ruff) and #27 (moto) separately from `/backend`, #29 (constructs) and #30 (aws-cdk-lib)
separately from `/infra`. The npm and github-actions groups worked correctly in the same wave
(#28 react, #31 vite, #33 in `actions-minor-patch`), so grouping is not broken in general.

**Not yet root-caused, and worth saying so rather than guessing.** The obvious difference is that
both pip manifests use **range** requirements (`>=x,<y`), for which Dependabot emits
"Update X requirement from…" PRs rather than "Bump X from…". The plausible mechanism is that
these requirement-updates aren't classified into the semver `update-types` buckets a group keyed
only on `update-types` needs — but `actions-minor-patch` is *also* keyed only on `update-types`
and did group, so that story is incomplete. A competing explanation for #26 specifically:
ruff is `0.x`, and Dependabot may treat `0.15 → 0.16` as semver-**major**, which would correctly
exclude it from a minor/patch group. That doesn't explain #27/#29/#30.

**The experiment** (cheap, one line each): add `patterns: ["*"]` to both pip groups so membership
is pattern-based rather than update-type-based, and see whether next month's run produces one PR
per pip directory. If majors then group too, that's arguably *right* for `/infra` — aws-cdk-lib
and constructs are coupled and should move together, the same reasoning behind the existing
react and vite groups.

**Why it's not urgent:** the failure mode is PR *volume*, not broken updates. Each solo PR is
individually valid and mergeable.

**Refs:** `.github/dependabot.yml`; the 2026-08 wave (#26–#34); `.claude/skills/dependabot-triage`.

---

### B-6 — `infra/requirements.txt` still has the exposure just fixed in `backend/` 🆕

**Noticed:** 2026-08-01 wave (triage). **Type:** tech-debt / reproducibility. **Likely home:**
the next infra-touching slice.

#35 tightened `backend/requirements-dev.txt` to compatible-minor bounds after ruff 0.16's
broadened defaults reddened `main` and every open PR at once. `infra/requirements.txt` still
carries the same shape:

```
aws-cdk-lib>=2.261.0,<3.0.0
constructs>=10.7.0,<11.0.0
```

There is no lockfile, so CI resolves the newest matching release on every run — during this
triage it installed **2.263.0 / 10.8.0**, well past the floors #29/#30 were proposing. The risk
is sharper than it was for a linter: `aws-cdk-lib` **generates the CloudFormation templates we
deploy**. A minor release can legitimately change synthesized output (new defaults, changed
logical-ID or metadata emission), which means the `cdk diff` reviewed locally and the templates
CI actually deploys can be produced by *different library versions* — silently weakening the
ADR-004 "review `cdk diff` before every deploy" habit.

Not observed to have caused a problem: the 2.261 → 2.263 bump showed no property drift when
diffed against the live dev stack during this triage.

**Fix when convenient:** bound to a compatible minor (`>=2.263.0,<2.264`) as `/backend` now is, or
adopt a proper lockfile (`pip-compile`/`uv`) for infra. The lockfile is the better end state
since infra is deploy-critical; the bound is the five-minute version.

**Refs:** `infra/requirements.txt`; #35; ADR-004; relates to [B-5].

---

### B-7 — Nothing can categorize the transactions imported before Slice 5 🆕

**Noticed:** 2026-08-02, driving the Slice 5 live exit criteria. **Type:** correctness / UX.
**Likely home:** Slice 6 — treat as a **blocker**, not a nice-to-have.

The importer enqueues only the rows it **newly added** (`enqueue_categorization(sub, added_keys)`).
That is correct for its job, but it means categorization can only ever happen *at import time*.
There is no path to categorize a transaction that already exists.

Dev currently holds **153 real transactions** from the owner's Slice-4 Chase imports, every one
at `categoryStatus: "uncategorized"`. They were imported before the categorizer existed, so they
were never enqueued — and re-uploading the same file cannot fix it, because file-hash and row
natural-key idempotency (ADR-012) mean a re-import adds **0 rows** and therefore enqueues **0**.
The data is stranded by design.

**Why this is a Slice 6 blocker specifically:** Slice 6 is the budget-vs-actual dashboard. Against
today's data it would render every category at $0 spent and 153 transactions under "Uncategorized"
— the product's core screen, demoing as empty, on real data. Fixing it after Slice 6 means the
dashboard is untrustworthy for its whole first outing.

**Options** (pick during Slice 6 planning):
- A one-shot **re-drive** — scan for `categoryStatus = uncategorized` in a window and enqueue them
  in batches. Smallest change; the categorizer is already idempotent and correction-preserving, so
  a re-drive is safe to run more than once.
- A **`POST /transactions/recategorize`** endpoint over a date window, which doubles as the manual
  re-run control the review queue (Slice 7) will want anyway.

The importer docstring already anticipates this — "a lost enqueue costs a re-drive at worst" — but
no re-drive mechanism was ever built.

**Refs:** `backend/functions/importer/handler.py` (~line 120); `backend/adapters/sqs.py`;
relates to [B-4] and to FR-3.5.

---

### B-8 — Eval baseline deferred until the app is further along 🔎

**Noticed:** 2026-08-02 (owner decision). **Type:** process / quality. **Likely home:** revisit
after Slice 7.

Slice 5 shipped `backend/eval/` (label/score harness, A/B across Opus 4.8 and Sonnet 5) and its
exit criteria included a baseline accuracy number per model. **Owner has deferred this**: the app
still lacks the dashboard (Slice 6) and the review queue (Slice 7), and the judgement is that
measuring categorization quality is more useful once there is a product to judge it against.

Recorded rather than dropped, because it is a real gap and the reason it is cheap to defer *now*
is exactly the reason it gets expensive later:

- The harness is **built and unit-tested**, so resuming is a matter of supplying labels, not code.
- Slice 7's review queue is the natural place labels come from — every correction the owner makes
  is a ground-truth label. Waiting until corrections exist means the eval set builds itself instead
  of being hand-authored.
- The countervailing risk: **the confidence threshold (0.8) is currently an unvalidated guess.**
  Until a baseline exists there is no evidence for where auto-assign should stop and review should
  start, so the review queue may be sized wrong in either direction. Note this when tuning it.

Also unblocked-by-then: as of 2026-08-02 the account cannot invoke either model at all (see the
Slice 5 completion notes on Bedrock model access), so an eval could not have run today regardless.

**Refs:** `backend/eval/`; ADR-008; Slice 5 exit criteria in `ledgerly-plan.md`; [B-7].

---

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-21 | Backlog doc created (seeded B-1 account picker, B-2 txn pagination/window, B-3 frontend visual pass). Boundary vs. the plan's post-MVP parking lot + the triage flow defined. |
