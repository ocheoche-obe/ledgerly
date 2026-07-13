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
- **Amazon Bedrock** — AWS's managed service for calling foundation models (incl.
  Claude) with IAM auth instead of an API key; spend lands on the AWS bill so the
  billing alarm covers it (ADR-008).
- **CDK (Cloud Development Kit)** — AWS's IaC framework where infrastructure is written
  in a real language (Python here) and synthesized to CloudFormation (ADR-004).
  `cdk diff` previews changes; reviewing it before deploys is a project habit.
- **DLQ (dead-letter queue)** — the SQS queue where messages land after exhausting
  retries; alarmed so failures are seen, and DLQ'd transactions stay `Uncategorized`
  rather than being lost (ADR-009, FR-3.5).
- **GSI (global secondary index)** — an alternate key arrangement over a DynamoDB table.
  Ledgerly: GSI1 = transactions by category, GSI2 = the review queue (sparse — items
  only exist in it while flagged).
- **On-demand capacity** — DynamoDB billing per request instead of provisioned
  throughput; ≈ $0 at single-user volume (ADR-005).
- **PITR (point-in-time recovery)** — DynamoDB continuous backup, restore to any second
  in the last 35 days; Ledgerly's no-data-loss backstop (NFR-3.1).
- **Presigned URL** — a time-limited signed S3 URL letting the browser upload the CSV
  directly to S3, so the file never transits a Lambda (architecture §3.1).

## 2. AI, ML & Agent Concepts

- **Categorization agent** — Ledgerly's LLM-based component that assigns each imported
  transaction to one of the owner's budget categories, with a confidence signal (FR-3).
- **Confidence signal** — the categorization agent's self-reported certainty per
  assignment; low-confidence items go to the review queue instead of being silently
  trusted (FR-3.2/3.3).
- **Few-shot examples** — prior owner corrections included in the agent's prompt so
  categorization accuracy improves with use (FR-3.4).
- **Eval harness** — a labeled set of real transactions plus a script that reports
  categorization accuracy per run; the gate for prompt/model changes and the measurement
  behind success criterion 2 (NFR-5.3; built in Slice 5).
- **Merchant rule** — a durable `normalized merchant → category` mapping created from an
  owner correction; checked before the LLM, so corrections make future imports faster,
  cheaper, and more accurate (FR-3.4, ADR-008).
- **Structured output** — constraining the LLM's response to a JSON schema so every
  categorization result parses as `{txnId, categoryId, confidence}` — no free-text
  parsing (ADR-008).

## 3. Software Engineering & Architecture

- **ADR (Architecture Decision Record)** — a short written record of a significant technical
  decision: context, decision, alternatives, consequences. Lives in the ADL.
- **Access-pattern-first** — the data-modeling method used in architecture §2: list every
  read/write the product performs, then design keys so each is a Get/Query/conditional
  Put — never a scan. The habit that makes single-table DynamoDB work.
- **Diagram as code** — generating architecture diagrams from a version-controlled script
  (`docs/render_architecture.py`, mingrammer `diagrams`) so the picture can't drift from
  the code; re-rendered in the same commit as any system-shape change.
- **Idempotency** — an operation that is safe to repeat: re-uploading a file or replaying
  a queue message produces the same state, no duplicates. Ledgerly enforces it at file,
  row, and message level (architecture §4.6).
- **Single-table design** — the DynamoDB pattern of storing all entity types in one table,
  distinguished by key prefixes (`CAT#`, `TXN#`, `BUDGET#`…), so related data is fetched
  in single queries (ADR-005).
- **Vertical slice** — a thin, end-to-end piece of functionality that touches every layer
  and ships deployed, rather than building one layer fully before the next.
- **Walking skeleton** — the thinnest possible end-to-end implementation (login → API →
  data → UI, deployed) proving the whole stack works before any real feature is built;
  Ledgerly's Slice 1.

## 4. Security & Networking

- **JWT (JSON Web Token)** — the signed token Cognito issues at login; API Gateway's JWT
  authorizer verifies it before any Lambda runs, and its `sub` claim is the user identity
  for all data scoping (FR-1.3, ADR-006/007).
- **Least privilege** — each component gets only the permissions it needs: one IAM role
  per Lambda, scoped to its table/queue/bucket/model (NFR-4.4, architecture §4.2).
- **OIDC + PKCE** — the standard, secret-free login flow for SPAs (Authorization Code
  with Proof Key for Code Exchange) used against Cognito's hosted UI. Also the mechanism
  GitHub Actions uses to assume the AWS deploy role without stored keys (Slice 2).

## 5. Frontend & Web

- **SPA (single-page application)** — the app ships as static files (S3/CloudFront) and
  runs entirely in the browser, calling the API with a bearer token; no server-side
  rendering (ADR-003).
- **Vite** — the frontend build tool/dev server for the React + TypeScript app.

## 6. Project-Specific Terms

- **Budget cycle** — the period a budget applies to: a calendar month (default) or a
  two-week span anchored to an owner-chosen, payday-aligned start date (FR-4.2). Budget
  amounts, the dashboard, and the check-in ritual all run per cycle.
- **Cycle ID** — the key form of a budget cycle: `M#2026-07` (monthly) or `B#2026-07-10`
  (two-week, by start date). Computed from settings, never stored on transactions, so a
  cadence change never rewrites history (architecture §2.1).
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
