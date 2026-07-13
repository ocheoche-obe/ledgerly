# Ledgerly — Architecture Document

**Version:** 0.1
**Status:** Drafting
**Last updated:** 2026-07-12

> Owns **HOW** (system design) and **WHERE** (§0.1 deployment target & environment). Every
> significant choice recorded here should have a matching ADR in `ledgerly-adl.md`
> that owns the **WHY**. If this doc and the plan doc ever disagree on design, this doc wins.
> Delete this note when real.

---

## 0. Overview

{{A short prose overview of the system: the shape of it in a paragraph, the major moving
parts, and the single most important architectural idea. Someone should be able to read
just this section and know roughly how the thing works.}}

### 0.1 Deployment target & environment — the WHERE

> Decide this *with the user* during the opening interview and record it as **ADR-001**.
> Keep the stack open until then — do not default to any particular cloud.

- **Target:** {{AWS / Azure / GCP / local laptop / self-hosted server / edge / mobile / hybrid}}
- **Why this target:** {{fit to the goal, cost, existing skills, learning objective — link ADR-001}}
- **Chosen stack:** {{compute, data, hosting, IaC/deploy tool — each anchored to an ADR}}
- **Runtime environments:** {{e.g. dev + prod; how many accounts/machines; how they differ}}
- **Portability posture:** {{what's cloud/host-specific vs. what could move; anything kept
  deliberately portable}}

---

## 1. System Architecture

### 1.1 Diagram

{{ASCII or a link to a rendered diagram (e.g. a render_architecture.py that regenerates a
PNG/PDF). Show the request/data flow across the major components.}}

```
{{user}} -> {{edge/CDN}} -> {{API}} -> {{compute}} -> {{data}} / {{AI}} / {{async}}
```

### 1.2 Rationale by layer

{{For each layer — frontend, API, compute, data, storage, AI, async/eventing, auth —
one short paragraph: what it is and why, linking the ADR that decided it.}}

### 1.3 What's deliberately not in v1

{{Architectural things you're consciously leaving out — GSIs, a queue, a cache, multi-region
— and the trigger that would make you add each.}}

### 1.4 Cross-cloud parallels (optional, learning aid)

{{If this is a learning vehicle, mapping the chosen services to their Azure/GCP equivalents
cements the concept. Optional.}}

---

## 2. Data Model

### 2.1 Methodology — access-pattern-first

{{List the access patterns FIRST (how data is read and written), then design keys to serve
them. This is the single most valuable habit from CareerVault's data-model work.}}

### 2.2 Access patterns

| # | Access pattern | Read/Write | Notes |
|---|---|---|---|
| 1 | {{...}} | | |

### 2.3 Entity model

{{The entities and their relationships.}}

### 2.4 Key design

{{PK/SK (or table/index) design that serves the access patterns above. Show the key schema.}}

### 2.5 Access patterns -> operations

{{Map each access pattern to the concrete query/operation that satisfies it. Prove the
key design works before writing code.}}

### 2.6 Sample item shapes

{{Example records/rows so the shape is unambiguous.}}

---

## 3. Sequence Diagrams

> One per non-trivial flow. These are where the design gets stress-tested before code.

### 3.1 {{Flow name, e.g. primary write path}}

{{Step-by-step: actor -> component -> component, including failure/retry behavior.}}

### 3.2 {{Flow name}}

---

## 4. Cross-Cutting Concerns

### 4.1 Observability
{{Logging fields, metrics, tracing conventions.}}

### 4.2 IAM / authz & least privilege
{{Per-component permissions posture; the invariant that identity comes from the auth token.}}

### 4.3 Secrets & configuration
{{Where config and secrets live; how they propagate.}}

### 4.4 Encryption
{{At rest and in transit.}}

### 4.5 Async / messaging surface
{{Queues, topics, dead-letter handling — if any.}}

### 4.6 Reliability
{{Retries, idempotency, timeouts, backpressure.}}

### 4.7 Operational hygiene
{{Backups, retention, deletion protection, cost guards.}}

---

## 5. Infrastructure-as-Code Structure

### 5.1 Template organization
{{Single template vs nested; what tool (SAM/CDK/Terraform) and why (link the ADR).}}

### 5.2 Repository layout
{{The tree — where functions/services, shared code, infra, tests, and docs live.}}

### 5.3 Environment strategy
{{dev/prod split, how many accounts, parameterization.}}

### 5.4 Deployment story
{{Manual for MVP vs CI/CD; the upgrade path.}}

---

## Change Log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-12 | Initial draft |
