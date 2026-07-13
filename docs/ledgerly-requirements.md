# Ledgerly — Requirements Document

**Version:** 1.0
**Status:** Approved (owner review 2026-07-13, with two amendments incorporated)
**Last updated:** 2026-07-13

> Owns **WHO** (§2 Users & Personas) and **WHAT** (everything else). Facts about *where*
> it runs and *how* it's built live in `ledgerly-architecture.md`; the *why* behind
> decisions lives in `ledgerly-adl.md`.

---

## 1. Purpose & Vision

Ledgerly is a personal budgeting and financial-planning app. It ingests the owner's bank
transaction history, uses an AI agent to categorize every transaction into the owner's own
budget categories, and presents an **at-a-glance view of budget vs. actual spending per
category** for the current **budget cycle** — a calendar month by default, with a two-week
payday-aligned option (most US jobs pay bi-weekly, and much real planning happens on that
rhythm). The owner defines the categories and sets a budget amount for each per cycle;
Ledgerly does the tedious part — turning a pile of raw transactions into an itemized,
categorized picture of where the money actually went.

**The one thing that must be true for Ledgerly to be worth building:** each month, the
owner can load their real transactions, have them categorized mostly correctly with
near-zero manual effort, and see in one glance how actual spending compares to budget per
category — and keeps coming back to do it. Automation of ingest (live bank connections)
deepens that value later, but the monthly at-a-glance review *is* the product.

**Secondary purpose — learning vehicle.** Ledgerly is explicitly an educational project.
The owner wants to learn AI-agent/LLM pipelines, AWS serverless architecture,
infrastructure-as-code + CI/CD, and frontend/full-stack skills by building it. This
changes how trade-offs are made: favor learning-rich, explainable choices over pure
expedience, and run the full agentic-engineering lifecycle rather than shortcutting it.

---

## 2. Users & Personas — the WHO

### v1

- **The owner (sole user and sole operator):** a software engineer building and using
  Ledgerly for their own finances. Uses the app in two modes:
  - **Monthly reviewer** — imports the month's transactions, corrects any
    mis-categorizations, and reads the budget-vs-actual dashboard.
  - **Budget planner** — occasionally creates/edits categories and adjusts monthly
    budget amounts.
- **Operator:** the same person. There is no separate ops persona; operational burden must
  therefore stay near zero (managed services, alarms rather than monitoring shifts).
- **Design constraint the whole system assumes:** single-user, but the **data model is
  multi-tenant-ready** — every record is scoped to a user identity from day one, so
  adding users later is an auth/product problem, not a data-migration problem.

### Future (designed-ready, not built)

- **Household member** — a partner sharing (parts of) a budget. Would introduce shared
  vs. personal categories and multi-user auth.
- **General end-user** — if Ledgerly ever became a product others sign up for. Would
  introduce self-signup, tenancy isolation guarantees, and compliance obligations around
  bank data. Nothing in v1 may *foreclose* this; nothing in v1 *builds* it.

---

## 3. Scope

### In scope for MVP (v1)

1. **Authentication** — real login for the single owner account; no anonymous access.
2. **CSV transaction import** — upload bank-export CSV files; safe to re-upload
   (idempotent, deduplicated).
3. **AI categorization** — an LLM-based agent assigns each imported transaction to one of
   the owner's categories, with a confidence signal; low-confidence items flagged for
   review.
4. **Manual correction** — the owner can re-categorize any transaction; corrections are
   remembered and improve future categorization.
5. **Categories & budgets** — create/edit/archive categories; set a budget amount per
   category per budget cycle. Cycle cadence is **monthly by default, with a two-week
   (payday-aligned) option**.
6. **At-a-glance dashboard** — budget vs. actual per category for the current budget
   cycle, with drill-down to the underlying transactions.

### Deferred (post-MVP, in priority order)

1. **Plaid live bank connection** — automatic transaction sync replacing/alongside CSV
   (sandbox first, then real accounts).
2. **Month-over-month trends** — spending trends across months beyond the current-month
   view.
3. **Recurring/subscription detection** — surface recurring charges as a distinct view.
4. **Alerts/notifications** — e.g. "you're at 80% of your dining budget."
5. **Savings goals** — save-$X-by-date tracking.
6. **Ask-my-finances chat** — conversational agent over the owner's data.

### Out of scope (explicitly not building)

- **Native mobile app** — the responsive web app is the phone experience; revisit only if
  it proves insufficient.
- **Multi-user / household sharing** — designed-ready only (§2).
- **Investment, net-worth, or asset tracking** — Ledgerly is about spending and budgets;
  it never follows money after it leaves the owner's accounts (no holdings, balances, or
  performance). **Clarification (in scope, not an exception):** money *contributed* to
  investments or savings during a cycle is an ordinary outflow — the owner can create an
  "Investments" category, budget for it, and track contributions against that budget like
  any other category (FR-4.1). Only the fate of those contributions is out of scope.
- **Money movement of any kind** — no payments, transfers, or bill pay, ever, in any
  version currently imagined.
- **Tax preparation/reporting.**

---

## 4. Functional Requirements

### FR-1 — Authentication & account

- **FR-1.1** — All access requires login; there is no anonymous or unauthenticated surface.
- **FR-1.2** — v1 has exactly one user account, provisioned by the owner; there is no
  self-signup flow.
- **FR-1.3** — Every stored record is scoped to the authenticated user's identity, taken
  from the auth token — never from request payloads.

### FR-2 — Transaction ingest

- **FR-2.1** — The owner can upload a transaction CSV exported from a bank; at minimum the
  formats of the owner's own banks are supported (date, description/merchant, amount,
  debit/credit direction; account identifiable per file at upload time).
- **FR-2.2** — Import is idempotent: re-uploading the same file, or overlapping exports,
  does not create duplicate transactions.
- **FR-2.3** — Ingest is a **pluggable source abstraction**: CSV is the first source, and
  a live bank-connection source (e.g. Plaid) must be addable later without reworking the
  downstream pipeline (categorization, budgets, dashboard).
- **FR-2.4** — The original imported data is preserved: each transaction keeps its raw
  source record alongside the normalized form Ledgerly works with.
- **FR-2.5** — An import reports what happened: how many transactions were added, skipped
  as duplicates, or failed to parse.

### FR-3 — AI categorization

- **FR-3.1** — Every ingested transaction is automatically assigned to exactly one of the
  owner's categories, or to a built-in **Uncategorized** bucket when no category fits.
- **FR-3.2** — Each automatic assignment carries a confidence signal.
- **FR-3.3** — Low-confidence assignments are flagged and surfaced as a review queue.
- **FR-3.4** — Owner corrections (FR-6.2/FR-6.3) are stored and used to improve future
  categorization (e.g. as few-shot examples or merchant→category rules), so accuracy
  rises with use.
- **FR-3.5** — Categorization runs asynchronously and must not block or fail an import;
  a transaction whose categorization fails lands in Uncategorized, never lost.

### FR-4 — Categories, budgets & budget cycles

- **FR-4.1** — The owner can create, rename, and archive spending categories. Any outflow
  is categorizable — including contributions to savings or investments (see §3
  clarification); Ledgerly does not judge what a category is "for."
- **FR-4.2** — Budgeting runs on a **budget cycle**. Two cadences are supported:
  **calendar month (default)** and **two-week**, anchored to an owner-chosen start date
  (payday-aligned). The owner sets the cadence once in settings and can change it;
  a cadence change takes effect from the next cycle and never rewrites past cycles.
- **FR-4.3** — Each category can have a budget amount per cycle; amounts can differ from
  cycle to cycle.
- **FR-4.4** — A sensible starter set of categories is offered at first run, fully
  editable.
- **FR-4.5** — Archiving/deleting a category requires an explicit choice for its
  transactions (reassign to another category or to Uncategorized); history is never
  orphaned or silently deleted.

### FR-5 — Dashboard & at-a-glance view

- **FR-5.1** — A single dashboard screen shows, for the current budget cycle:
  per-category budget vs. actual spend, and overall totals (money in, money out, remaining
  budget).
- **FR-5.2** — Each category drills down to its transactions for the cycle.
- **FR-5.3** — The dashboard can be viewed for past cycles, not just the current one.
- **FR-5.4** — The dashboard is fully usable on a phone browser (responsive).

### FR-6 — Transaction management

- **FR-6.1** — A transaction list view exists with filter/search (by date range, category,
  amount, and description text).
- **FR-6.2** — The owner can change any transaction's category from the list or drill-down
  views (single action; this is the FR-3.4 correction signal).
- **FR-6.3** — The review queue (FR-3.3) supports quick confirm-or-correct triage.

---

## 5. Non-Functional Requirements

### Cost

- **NFR-1.1** — **Hard ceiling: $10/month** for everything the running app consumes
  (cloud infrastructure, AI/LLM API calls) at single-user volume. Any future paid bank
  connection (Plaid production) is a deliberate ceiling revision recorded as an ADR
  *before* it's incurred — not a silent overrun.
- **NFR-1.2** — A billing alarm/budget guard exists from the first deployed slice, set
  below the ceiling.

### Performance

- **NFR-2.1** — Dashboard renders its at-a-glance view in under ~2 seconds on a normal
  connection.
- **NFR-2.2** — A typical monthly import (a few hundred transactions) is fully ingested
  and categorized within ~2 minutes, with visible progress/status (async is fine; silent
  is not).
- **NFR-2.3** — Interactive actions (re-categorize, edit budget) feel immediate (<~500 ms
  perceived).

### Reliability & availability

- **NFR-3.1** — **No data loss is the reliability bar.** Financial records, once ingested,
  survive failures: durable storage, idempotent ingest, and no destructive operation
  without an explicit user action.
- **NFR-3.2** — Availability is best-effort (single user, no SLA); a failed request may be
  retried by the user, but must never corrupt or duplicate data.

### Security (sensible-by-default posture)

- **NFR-4.1** — Authentication via a managed identity provider; no hand-rolled credential
  storage.
- **NFR-4.2** — All data encrypted in transit (TLS) and at rest.
- **NFR-4.3** — Secrets (API keys, tokens) live in a secrets manager, never in code,
  config files, or the repo.
- **NFR-4.4** — Least-privilege access between components (each component can touch only
  what it needs).
- **NFR-4.5** — **Bank credentials are never stored, ever.** When live bank connections
  arrive, only provider-issued access tokens are held (per NFR-4.3).
- **NFR-4.6** — Financial data is never sent to third parties except the minimum required
  for the function being performed (e.g. transaction descriptions to the LLM for
  categorization — and that flow is documented).

### Maintainability & operability

- **NFR-5.1** — All infrastructure is defined as code; nothing hand-created in a console
  survives past the slice that touched it.
- **NFR-5.2** — Deploys are automated (CI/CD) by the end of the first implementation
  phase; every slice ships deployed, per the lifecycle.
- **NFR-5.3** — Each slice carries tests; the categorization agent specifically has a
  measurable accuracy check, not vibes (see §7).
- **NFR-5.4** — Docs stay current per the kit's rules: a new session can cold-start from
  `CLAUDE.md` alone.

### Extensibility (owner-requested, first-class)

- **NFR-6.1** — The system stays **open-ended for future features**: ingest sources are
  pluggable (FR-2.3), categorization sits behind a swappable interface (model/provider can
  change), and internals are event-driven enough that new features (alerts, trends,
  recurring detection, chat) subscribe to existing data/events rather than requiring
  rewiring.

### Usability

- **NFR-7.1** — "At a glance" is a testable claim: the current cycle's budget position is
  understandable from one screen without scrolling on desktop, within seconds.
- **NFR-7.2** — The check-in ritual (import → triage review queue → read dashboard) takes
  under ~15 minutes of owner effort per budget cycle.

---

## 6. Constraints & Assumptions

### Technical constraints

- Deployment target: **AWS, serverless-first** (ADR-001). Component choices follow in the
  architecture stage.
- Backend language: **Python** (owner preference from the interview; confirmed as ADR-002
  in the architecture stage).
- Owner's bank accounts are **US-based** (relevant to the deferred Plaid work).

### Business constraints

- Solo developer, steady side-project pace (evenings/weekends), **no calendar deadline**.
  Slices are sized to be finishable in one or two sessions.
- $10/month cost ceiling (NFR-1.1).

### Assumptions (revisit if they break)

- The owner's banks all offer CSV/file export of transactions.
- Personal transaction volume: on the order of hundreds of transactions/month, low
  thousands/year.
- Transaction descriptions are English-language US-merchant strings (affects
  categorization prompt design).
- LLM API pricing at this volume stays negligible relative to the ceiling.

---

## 7. Success Criteria

Ledgerly v1 has succeeded if, and only if:

1. **The check-in ritual is real:** the owner has imported and reviewed **three
   consecutive months** of their own real transactions in the deployed app (not
   localhost) — that's 3 monthly cycles or ~6 two-week cycles, whichever cadence is in
   use.
2. **Categorization mostly just works:** ≥ **80%** of transactions are auto-categorized
   correctly (measured as 1 − correction rate over a month's import), trending up as
   corrections accumulate (FR-3.4). Aspirational: 90%+ by the third month.
3. **At-a-glance is true:** the owner can answer "where is my money going this cycle, and
   am I over budget anywhere?" from one dashboard screen (NFR-7.1).
4. **The ceiling held:** every month's total run cost ≤ $10 (NFR-1.1), verified from
   billing, not estimates.
5. **The lifecycle was run, not skipped:** every slice shipped deployed via IaC with
   tests, docs current throughout, and `ledgerly-evaluation.md` has a completed v1
   retrospective. (This is the learning-goal criterion.)

---

## 8. Resolved Open Questions

- **Q:** Single-user or multi-tenant? — **A:** Single-user; data model multi-tenant-ready.
  (Interview, 2026-07-12.)
- **Q:** Website or mobile app? — **A:** Responsive web app for v1; native mobile out of
  scope, revisit only if the phone-browser experience proves insufficient. (2026-07-12.)
- **Q:** Bank connection or file import first? — **A:** CSV import first; live bank
  connection (Plaid, sandbox first) is the top deferred item. Ingest built pluggable so it
  slots in. (2026-07-12.)
- **Q:** Cost ceiling? — **A:** $10/month hard; Plaid production would be a deliberate,
  ADR-recorded revision. (2026-07-12.)
- **Q:** Deployment target? — **A:** AWS serverless-first — see ADR-001. (2026-07-12.)
- **Q:** Security posture for v1? — **A:** Sensible-by-default (managed auth, encryption,
  secrets manager, least privilege); not full fintech rigor, not shared-secret minimalism.
  (2026-07-12.)
- **Q:** Promote any deferred feature into v1? — **A:** No — v1 stays thin; extensibility
  NFR-6.1 keeps the door open. (2026-07-12.)
- **Q:** Monthly budgeting only? — **A:** No — budget cycles support two cadences:
  calendar month (default) and two-week, anchored to a chosen start date, because US
  payroll is commonly bi-weekly and the owner plans on that rhythm. (Owner review,
  2026-07-13; FR-4.2.)
- **Q:** Can investment/savings contributions be budgeted, given investment tracking is
  out of scope? — **A:** Yes — contributions are ordinary outflows and fully
  categorizable/budgetable (e.g. an "Investments" category). What stays out of scope is
  tracking the money after it leaves: holdings, balances, performance. (Owner review,
  2026-07-13; §3, FR-4.1.)

---

## 9. Glossary

See `ledgerly-glossary.md` for the running glossary.

---

## 10. Change Log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-12 | Initial draft from opening interview; awaiting owner review |
| 1.0 | 2026-07-13 | Owner review: approved with two amendments — (1) budget cycles gain a two-week payday-aligned cadence option alongside the monthly default (FR-4.2/4.3, §1, §3, FR-5, NFR-7, §7); (2) clarified that investment/savings *contributions* are budgetable outflows while investment tracking stays out of scope (§3, FR-4.1). Also fixed FR-3.4 cross-references. |
