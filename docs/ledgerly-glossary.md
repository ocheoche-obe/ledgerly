# Ledgerly — Running Glossary

**Status:** Living document — grows as the project does
**Last updated:** 2026-07-13

---

## How this is organized

Terms are grouped by category. Add an entry the first time a term shows up that you had to
look up or that a teammate/future-you would. Keep definitions short and in your own words —
if this is a learning vehicle, writing the definition *is* the learning.

### Categories

1. Cloud services & concepts
2. AI / ML / agent concepts
3. Software engineering & architecture
4. Security & networking
5. Frontend & web
6. Project-specific terms

---

## 1. Cloud Services & Concepts

- **Serverless-first** — an architectural posture: prefer managed, pay-per-use services
  (functions, managed APIs, serverless data stores) over provisioned servers. Ledgerly's
  deployment posture per ADR-001; near-zero idle cost for a single-user app.

## 2. AI, ML & Agent Concepts

- **Categorization agent** — Ledgerly's LLM-based component that assigns each imported
  transaction to one of the owner's budget categories, with a confidence signal (FR-3).
- **Confidence signal** — the categorization agent's self-reported certainty per
  assignment; low-confidence items go to the review queue instead of being silently
  trusted (FR-3.2/3.3).
- **Few-shot examples** — prior owner corrections included in the agent's prompt so
  categorization accuracy improves with use (FR-3.4).

## 3. Software Engineering & Architecture

- **{{Term}}** — {{...}}.
- **ADR (Architecture Decision Record)** — a short written record of a significant technical
  decision: context, decision, alternatives, consequences. Lives in the ADL.
- **Vertical slice** — a thin, end-to-end piece of functionality that touches every layer
  and ships deployed, rather than building one layer fully before the next.

## 4. Security & Networking

- **{{Term}}** — {{...}}.

## 5. Frontend & Web

- **{{Term}}** — {{...}}.

## 6. Project-Specific Terms

- **Budget cycle** — the period a budget applies to: a calendar month (default) or a
  two-week span anchored to an owner-chosen, payday-aligned start date (FR-4.2). Budget
  amounts, the dashboard, and the check-in ritual all run per cycle.
- **Budget vs. actual** — the core dashboard comparison: the amount the owner budgeted
  for a category this cycle vs. what was actually spent in it (FR-5.1).
- **Check-in ritual** — the product's core loop, once per budget cycle: import
  transactions → triage the review queue → read the dashboard. Success criterion 1
  requires three consecutive real months of it (≈3 monthly or ~6 two-week cycles).
- **Ingest source** — a pluggable origin of transactions. v1 has one (CSV upload); a live
  bank connection (Plaid) is the planned second (FR-2.3).
- **Plaid** — a third-party bank-data aggregator; candidate provider for live transaction
  sync (deferred). Free sandbox with fake banks; paid per connected account in production.
- **Review queue** — the list of low-confidence categorizations awaiting quick
  confirm-or-correct triage (FR-3.3, FR-6.3).
- **Uncategorized** — the built-in fallback bucket for transactions no category fits or
  whose categorization failed; nothing is ever dropped (FR-3.1, FR-3.5).
