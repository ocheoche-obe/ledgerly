# Ledgerly — Implementation Plan & Roadmap

**Status:** Living document — the authoritative "what order, what's done, what's next"
**Version:** 0.1
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
   budget-posture check.
5. **Learning vehicle.** When live cloud behavior contradicts the docs, surface the
   contradiction and correct the doc with reasoning — never silently code around it.
6. **Close the loop.** Every slice ends with a short evaluation beat; every release ends with
   a retrospective in `ledgerly-evaluation.md`. Findings route to a requirement, an
   ADR, a slice, or the parking lot — never nowhere.

---

## Status board

| Slice | Name | Reqs covered | Status | PR |
|---|---|---|---|---|
| P0 | Requirements | — | ✅ approved v1.0 (2026-07-13) | — |
| P1 | Architecture design + foundational ADRs | — | ⬜ next | — |
| 1+ | Implementation slices | — | ⬜ sliced during P1, recorded here | — |

> Slice 1 will be the thinnest possible thing that proves the whole stack works
> end-to-end (auth → API → compute → data, deployed), per the kit's rule. The working
> candidate from the interview: **CSV upload → stored transactions → visible in a deployed
> UI** — with AI categorization as the immediate follow-on slice. Final slicing happens
> after the architecture stage.

---

## Completed slices

### Phase 0 — Requirements ✅
Completed 2026-07-13. Opening interview run 2026-07-12 (all six questions answered; see
requirements §8 for resolved questions); `ledgerly-requirements.md` drafted, owner-reviewed,
and approved as **v1.0** with two amendments: two-week budget-cycle cadence option added
alongside the monthly default (FR-4.2), and investment/savings *contributions* confirmed
budgetable while investment tracking stays out of scope (§3). ADR-001 (AWS,
serverless-first) recorded during setup.

### Phase 1 — Architecture design
_Not started — next up. Inputs: requirements v1.0, ADR-001; outputs: architecture doc
(incl. §0.1 WHERE), ADR-002…008 resolved, implementation slices written into this doc.
Note for the data model: budgets are per-cycle (monthly or two-week anchored), not
per-calendar-month — design keys/queries accordingly._

---

## Implementation slices

_To be written at the end of Phase 1, when the architecture is settled enough to slice
honestly. Each slice will follow the kit's shape: goal, key refs, scope in/out, ⚠ open
decisions, exit criteria (implemented / tested / deployed / docs / evaluation beat),
completion notes._

---

## Post-MVP parking lot

> Everything deferred lives here and *nowhere else*, so the slice sections stay honest.
> (Mirrors requirements §3 "Deferred"; this list carries the delivery-order notes.)

- **Plaid live bank connection** — top deferred item; sandbox first. Trigger: v1 monthly
  ritual proven (success criterion 1) and owner appetite to revise the cost ceiling
  (ADR required per NFR-1.1).
- **Month-over-month trends** — cheapest promotion; mostly queries + dashboard work once
  months of data exist. Trigger: 2–3 months of real data in the system.
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
