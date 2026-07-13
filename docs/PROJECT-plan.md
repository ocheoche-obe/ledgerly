# {{PROJECT_NAME}} — Implementation Plan & Roadmap

**Status:** Living document — the authoritative "what order, what's done, what's next"
**Version:** 0.1
**Created:** {{YYYY-MM-DD}}

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
| `{{project-slug}}-requirements.md` | **Who / What** | users & personas; functional/non-functional requirements |
| `{{project-slug}}-architecture.md` | **How / Where** | system design, data model, contracts, deployment target |
| `{{project-slug}}-adl.md` | **Why** | every significant decision, as ADRs |
| **This document** | **When** | slice sequence & order, scope, status, completion notes |
| `{{project-slug}}-evaluation.md` | — | stage-6 metrics & retrospectives that feed the next cycle |
| `CLAUDE.md` | — | compact session-start context; its phase marker just *points here* |

If this doc contradicts the architecture doc on a design matter, the architecture doc wins
and this doc gets fixed (or the contradiction becomes an ADR).

### The delivery lifecycle (this doc drives it)

Work runs the six-stage cycle from `KICKOFF.md`: **Requirements → Architecture →
Implementation → Testing → Deployment → Evaluation → (loop)**. Stages 3–5 (implementation,
testing, deployment) happen *inside each vertical slice* — a slice isn't done until it's
built, tested, and deployed. Stage 6 (evaluation) happens as a short beat at `/wrap-slice`
and as a fuller retrospective per release, both recorded in `{{project-slug}}-evaluation.md`,
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
4. **Cost ceiling.** {{$N/month}}. Slices that add a new paid service start with a
   budget-posture check.
5. **Learning vehicle.** When live cloud behavior contradicts the docs, surface the
   contradiction and correct the doc with reasoning — never silently code around it.
6. **Close the loop.** Every slice ends with a short evaluation beat; every release ends with
   a retrospective in `{{project-slug}}-evaluation.md`. Findings route to a requirement, an
   ADR, a slice, or the parking lot — never nowhere.

---

## Status board

| Slice | Name | Reqs covered | Status | PR |
|---|---|---|---|---|
| P0 | Requirements | — | 🔨 | — |
| P1 | Architecture design | — | ⬜ | — |
| 1 | {{first thin end-to-end slice}} | {{FR-1}} | ⬜ ⚠ | — |
| 2 | {{...}} | {{...}} | ⬜ ⚠ | — |
| 3 | {{...}} | {{...}} | ⬜ ⚠ | — |

> Slice 1 should be the thinnest possible thing that proves the whole stack works
> end-to-end (auth -> API -> compute -> data, deployed). Everything after builds on a
> known-good spine.

---

## Completed slices

### Phase 0 — Requirements
{{Completion notes once done.}}

### Phase 1 — Architecture design
{{Completion notes once done.}}

---

## Slice 1 — {{name}} ⬜ ⚠

**Goal:** {{one sentence — the user-visible or system capability this slice delivers}}

**Key refs:** {{ADRs and architecture sections this slice depends on}}

**Scope — in:**
- {{...}}

**Scope — out (deferred):**
- {{...}}

**⚠ Open decisions (resolve at /start-slice, capture as ADRs):**
- {{...}}

**Exit criteria:**
- [ ] {{implemented}}
- [ ] {{unit tests green + smoke-tested end-to-end}} _(stage 4: testing)_
- [ ] {{deployed to dev}} _(stage 5: deployment)_
- [ ] {{docs current}}
- [ ] {{evaluation beat recorded in the evaluation doc}} _(stage 6)_

**Completion notes:** _(filled at /wrap-slice)_

---

## Slice 2 — {{name}} ⬜ ⚠

{{same shape as slice 1}}

---

## Post-MVP parking lot

> Everything deferred lives here and *nowhere else*, so the slice sections stay honest.

- {{deferred idea}} — {{why deferred / trigger to pick it up}}

---

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | {{YYYY-MM-DD}} | Initial roadmap |
