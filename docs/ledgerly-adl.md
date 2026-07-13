# Ledgerly — Architectural Decisions Log (ADL)

**Status:** Living document — updated as decisions are made
**Last updated:** 2026-07-12

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

- Requirements: `ledgerly-requirements.md`
- Architecture: `ledgerly-architecture.md`
- Glossary: `ledgerly-glossary.md`
- Scoping notes: `ledgerly-reference.md`

### Convention

**ADR before code.** A decision the architecture doc doesn't already cover gets written
here *before* the code that implements it. Number ADRs sequentially and never renumber —
if a decision is reversed, add a new ADR that supersedes the old one and mark the old one
Superseded.

---

## Index

| ID      | Title                                            | Status   |
|---------|--------------------------------------------------|----------|
| ADR-001 | Deployment target: AWS, serverless-first         | Accepted |
| ADR-002 | Backend language / runtime                       | Open — architecture stage (Python strongly preferred per interview) |
| ADR-003 | Frontend stack                                   | Open — architecture stage |
| ADR-004 | Infrastructure-as-Code tool                      | Open — architecture stage |
| ADR-005 | Database + data-model approach                   | Open — architecture stage |
| ADR-006 | Tenancy model                                    | Open — architecture stage (interview direction: single-user, multi-tenant-ready data model) |
| ADR-007 | Authentication approach                          | Open — architecture stage (interview direction: managed IdP, sensible-by-default posture) |
| ADR-008 | AI categorization approach (model, pipeline)     | Open — architecture stage |

---

## ADR-001: Deployment target — AWS, serverless-first

**Status:** Accepted (2026-07-12, opening interview)

### Context

Ledgerly needs a deployment target (the WHERE). The constraints that drive it:

- **Single user** at personal transaction volume — traffic is near zero most of the time,
  bursty around a monthly import-and-review session.
- **Hard cost ceiling of ~$0–10/month** (NFR-1.1) — an always-on server or database eats
  most of that ceiling doing nothing.
- **Learning is a primary goal**: the owner explicitly wants to learn AWS serverless
  architecture, IaC/CI-CD, and AI/LLM pipelines, and has more existing access to AWS than
  to any other platform.
- **Python** is the owner's preferred backend language and is a first-class serverless
  runtime on AWS.

The starter kit requires this decision be made deliberately, not defaulted.

### Decision

Deploy Ledgerly to **AWS, single-cloud, serverless-first**: prefer managed, pay-per-use
services (e.g. Lambda-class compute, managed API front door, serverless data store,
managed identity) over provisioned servers or containers. Specific service choices are
made per-component in the architecture stage (ADR-002 onward), but each choice starts
from "the serverless option, unless there's a recorded reason not to."

### Alternatives considered

- **AWS with containers/EC2 (always-on)** — simpler mental model, but idle compute cost
  alone approaches the monthly ceiling, and it teaches less of what the owner wants to
  learn. Rejected on cost + learning fit.
- **Another cloud (GCP, Azure)** — comparable serverless offerings, but the owner has the
  most access and familiarity on AWS, and no requirement pulls toward another provider.
  Rejected on access/learning fit.
- **Local / self-hosted first** — zero cost and zero third-party risk, but it defers the
  cloud learning that motivates the project and gives no real deployment stage
  (lifecycle stage 5 would degenerate to "runs on my laptop"). Rejected.
- **PaaS (Fly.io, Render, Vercel-only)** — fastest to ship, but hides exactly the
  infrastructure the owner wants to learn. Rejected on learning fit.

### Consequences

- Near-zero idle cost; the app comfortably fits the ~$10/month ceiling at personal volume.
- The learning goals (serverless, IaC, event-driven design) get first-class exercise.
- **Accepted trade-off: vendor coupling to AWS.** Portability posture is documented in the
  architecture doc §0.1; business logic is kept separable from AWS plumbing but no
  active multi-cloud abstraction is built.
- Accepted trade-off: cold starts and distributed-system debugging complexity — fine for a
  single user, and itself a learning surface.
- Every later component ADR (002–008) inherits this posture as its starting context.

---

<!-- Copy the ADR block above for each new decision. Keep them append-only. -->
