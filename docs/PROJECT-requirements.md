# {{PROJECT_NAME}} — Requirements Document

**Version:** 0.1
**Status:** Drafting — requirements gathering in progress
**Last updated:** {{YYYY-MM-DD}}

> Owns **WHO** (§2 Users & Personas) and **WHAT** (everything else). If a fact about *where*
> it runs, *how* it's built, or *why* a choice was made shows up here, it belongs in the
> architecture doc or the ADL instead. Delete this note when real.

---

## 1. Purpose & Vision

{{One or two paragraphs: what this app is, the core value proposition, and — importantly —
what the *primary* value is versus secondary outputs. Be specific about the one thing that
must be true for this to be worth building.}}

{{If this is a learning vehicle, say so explicitly as a secondary purpose — it changes how
trade-offs get made (favor learning-rich, explainable choices over pure expedience).}}

---

## 2. Users & Personas — the WHO

> Nail this down in the opening interview. Even a single-user project should state it
> explicitly, because "who uses it and who operates it" shapes auth, tenancy, and scope.

### v1
{{Who is the sole/primary user for v1? Who operates/runs it? State the constraint the whole
design assumes (e.g. single-user, data model multi-tenant-ready).}}

### Future
{{Personas you're designing to be *ready* for but not building for yet.}}

---

## 3. Scope

### In scope for MVP (v1)
- {{...}}

### Deferred (post-MVP)
- {{...}}

### Out of scope (explicitly not building)
- {{...}}

> The "out of scope" list is as valuable as the "in scope" list — it stops scope creep and
> records what you consciously decided *not* to do.

---

## 4. Functional Requirements

> Number these FR-1, FR-2, … and sub-number (FR-2.1) so the plan doc can map slices to them.

### {{Capability area, e.g. Authentication & user management}}
- **FR-1.1** — {{requirement}}
- **FR-1.2** — {{requirement}}

### {{Capability area}}
- **FR-2.1** — {{requirement}}

---

## 5. Non-Functional Requirements

> Number these NFR-1, NFR-2, … Group by concern.

### Cost
- **NFR-1.1** — {{hard monthly ceiling and what it covers}}

### Performance
- **NFR-2.1** — {{latency / throughput targets that actually matter for v1}}

### Reliability & availability
- **NFR-3.1** — {{...}}

### Security
- **NFR-4.1** — {{authn/authz, data protection, secrets handling}}

### Maintainability
- **NFR-5.1** — {{...}}

### Usability
- **NFR-6.1** — {{...}}

---

## 6. Constraints & Assumptions

### Technical constraints
- {{must-use / must-avoid services, region, runtime versions, account limits}}

### Business constraints
- {{budget, timeline, solo developer, etc.}}

### Assumptions
- {{things you're taking as given; revisit if they break}}

---

## 7. Success Criteria

{{Concrete, checkable statements of "we succeeded if…". These become the north star the
plan's slices ladder up to.}}

---

## 8. Resolved Open Questions

> As requirements-gathering questions get answered, record the answer here so they don't
> get relitigated. Move unresolved ones to the plan doc's ⚠ decisions if they block work.

- **Q:** {{question}} — **A:** {{resolution + date}}

---

## 9. Glossary

See `{{project-slug}}-glossary.md` for the running glossary.

---

## 10. Change Log

| Version | Date | Change |
|---|---|---|
| 0.1 | {{YYYY-MM-DD}} | Initial draft |
