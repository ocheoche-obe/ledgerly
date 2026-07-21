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

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-21 | Backlog doc created (seeded B-1 account picker, B-2 txn pagination/window, B-3 frontend visual pass). Boundary vs. the plan's post-MVP parking lot + the triage flow defined. |
