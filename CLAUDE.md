# {{PROJECT_NAME}} — Project Context for Claude Code

> This file is loaded at the start of every Claude Code session. Keep it current
> as the project evolves. The phase marker at the bottom is especially important.
>
> TEMPLATE NOTE: keep this file COMPACT. It is session-start context, not documentation.
> Anything that grows or changes often belongs in the plan/architecture/ADL docs, and
> this file just points at them. Delete this note once the project is real.

## How this project is run

Built with agentic-engineering discipline: a six-stage lifecycle run as a cycle —
**Requirements → Architecture → Implementation → Testing → Deployment → Evaluation →
(loop)** — and a doc set where each document owns exactly one of the six questions
(**who/what** = requirements, **where/how** = architecture, **why** = ADL, **when** = plan).
See `KICKOFF.md` for the full framework.

## What this app does

{{ONE_PARAGRAPH: what the app does, for whom, and the core value proposition. Pull this
straight from the requirements doc's Purpose & Vision once it exists.}}

{{Tenancy / scale posture in one line — e.g. "Single-user MVP, data model designed to be
multi-tenant-ready." Reference the ADR that decided it.}}

## Canonical docs (always trust these first)

- **`docs/{{project-slug}}-architecture.md`** — full architecture document. Authoritative
  source for system design, data model, sequence diagrams, cross-cutting concerns, IaC.
- **`docs/{{project-slug}}-plan.md`** — implementation plan & roadmap. Authoritative for
  slice order, per-slice scope/exit criteria, status, and completion notes.
- **`docs/{{project-slug}}-requirements.md`** — functional and non-functional requirements.
- **`docs/{{project-slug}}-adl.md`** — Architectural Decision Records. The "why" behind
  every significant choice.
- **`docs/{{project-slug}}-evaluation.md`** — lifecycle stage 6: metrics, retrospectives,
  and the findings that seed the next cycle.
- **`docs/{{project-slug}}-glossary.md`** — terms, services, cross-cloud parallels.
- **`docs/{{project-slug}}-reference.md`** — original scoping notes / brain-dump.

When making implementation decisions, consult the architecture doc first. If something
seems off or unclear, the ADL captures the reasoning behind it.

## Architecture summary

{{FILL FROM THE ARCHITECTURE DOC once Phase 1 is done. A compact bullet list of the major
components and the ADR that anchors each. Example shape below — replace with reality:}}

- **Frontend:** {{stack}} (ADR-00X), hosted on {{...}}.
- **API:** {{...}}.
- **Backend:** {{language/runtime}} (ADR-00X), packaged via {{IaC tool}} (ADR-00X).
- **Database:** {{...}} (ADR-00X).
- **Storage / AI / Notifications / etc.:** {{...}}.
- **Region:** {{region}} (ADR-00X).

## Components / functions

{{List the deployable units (Lambdas, services, containers…) and one line on each purpose.
Point at the architecture-doc section with the full contracts.}}

## Repository layout

```
{{fill once the repo shape is decided — keep it to the top-level map}}
docs/                # Architecture, requirements, ADL, glossary
CLAUDE.md            # This file
```

## Conventions

{{Language/runtime conventions, handler signatures, shared-code import paths, logging and
metrics conventions, security invariants (e.g. "user ID comes from the auth token, never
the request body"). Fill as they solidify — usually end of the first implementation slice.}}

## Cost constraints

- **{{$N/month}} effective hard ceiling.** {{one line on why that number}}.
- Guards in place: {{budget alarm name, billing alarms, log retention, per-resource caps}}.

## Current build phase

**Phase {{N}} — {{phase name}} ({{status}}). Current slice: {{N}} — {{short name}}.**

- Last completed: {{slice}} ({{PR link}}).
- **The roadmap lives in `docs/{{project-slug}}-plan.md`** — slice order, per-slice scope,
  exit criteria, open decisions, and completion notes. Read the status board + current
  slice section at session start; update it when a slice wraps.
- Session rituals: `/start-slice` and `/wrap-slice` (project skills in `.claude/skills/`).

Refer to the architecture doc as you implement. If a decision needs to be made that isn't
covered, capture it as a new ADR in `{{project-slug}}-adl.md` before coding it in.
