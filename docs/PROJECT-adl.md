# {{PROJECT_NAME}} — Architectural Decisions Log (ADL)

**Status:** Living document — updated as decisions are made
**Last updated:** {{YYYY-MM-DD}}

---

## What this is

This file captures the **why** behind significant architectural choices. Each entry is an
**Architecture Decision Record (ADR)** — a lightweight written record of a decision, the
context around it, the alternatives considered, and the consequences accepted.

ADRs are an industry-standard practice because architectural reasoning fades fast: six
months from now, "why did we pick X over Y?" becomes unanswerable unless it's written
down. ADRs preserve that institutional memory.

### Format used here

Each ADR has:
- **Status** — Accepted (decided), Proposed (leaning), Open (TBD), Deferred (revisit later),
  Superseded (replaced by a later ADR — link it).
- **Context** — what situation forced the decision.
- **Decision** — what was chosen.
- **Alternatives considered** — what was rejected and why.
- **Consequences / trade-offs** — what's gained, and what's accepted as cost or risk.

### Cross-reference

- Requirements: `{{project-slug}}-requirements.md`
- Architecture: `{{project-slug}}-architecture.md`
- Glossary: `{{project-slug}}-glossary.md`
- Scoping notes: `{{project-slug}}-reference.md`

### Convention

**ADR before code.** A decision the architecture doc doesn't already cover gets written
here *before* the code that implements it. Number ADRs sequentially and never renumber —
if a decision is reversed, add a new ADR that supersedes the old one and mark the old one
Superseded.

---

## Index

| ID      | Title                                       | Status   |
|---------|---------------------------------------------|----------|
| ADR-001 | {{Cloud provider — e.g. AWS single-cloud}}  | {{Accepted}} |
| ADR-002 | {{Backend language / runtime}}              | {{...}}  |
| ADR-003 | {{Frontend stack}}                          | {{...}}  |
| ADR-004 | {{Infrastructure as Code tool}}             | {{...}}  |
| ADR-005 | {{Database + data-model approach}}          | {{...}}  |
| ADR-006 | {{Tenancy model}}                           | {{...}}  |
| ADR-007 | {{Authentication approach}}                 | {{...}}  |

> Add a row per ADR as you write it. The first ~7 decisions (provider, runtime, frontend,
> IaC, database, tenancy, auth) are the usual foundation — but write only the ones your
> project actually faces.

---

## ADR-001: {{Title}}

**Status:** {{Accepted}}

### Context
{{What situation forced this decision? What requirement or constraint is driving it?}}

### Decision
{{What did we choose? Be specific.}}

### Alternatives considered
- **{{Alternative}}** — {{why rejected}}.
- **{{Alternative}}** — {{why rejected}}.

### Consequences
- {{What we gain.}}
- {{What we accept as cost, risk, or future work.}}

---

## ADR-002: {{Title}}

**Status:** {{...}}

### Context
{{...}}

### Decision
{{...}}

### Alternatives considered
- {{...}}

### Consequences
- {{...}}

---

<!-- Copy the ADR block above for each new decision. Keep them append-only. -->
