# PLAID_PLAN.md

Durable state of the Plaid integration build (Plaid build kit). Design decisions and their
reasoning live in `docs/ledgerly-adl.md` (ADR-014); slice scope and exit criteria live in
`docs/ledgerly-plan.md` (Slice 9). This file does not repeat them.

## Goal

Pivot Ledgerly's ingest from CSV upload to Plaid: a personal budget tracker (single user),
Transactions product, Sandbox only for this slice. (workflow_id: wf_59c10ba6072e44b7)

## Scope

- Products:
  - `transactions` — the spending history the budget dashboard is built on (SELECT-001), via
    `/transactions/sync` only (TXN-001). The only entry in Link's `products` (SELECT-015,
    CONV-001).
  - `identity` — in `additional_consented_products` only: consented now, not called, not billed,
    so account-ownership verification can be added later without re-consent (CONV-002, CONV-011).
  - Account balances — the cached balances that come with the account list; not the Balance
    product (SELECT-005).
- Rejected: Balance real-time checks (billed per call, 3–11 s; BAL-001/002) · Assets (lending
  snapshot; SELECT-009) · Enrich (only helps CSV-imported rows; not among this account's enabled
  products) · investments / liabilities (owner scoped this to spending; add-later candidates).
- Platform: Python 3.13 AWS Lambda backend (boto3, no runtime deps) + React/Vite/TypeScript SPA
  (`react-plaid-link`, WEB-020).
- Environment: sandbox until acceptance passes. US only.
- Owner's scope answers (verbatim): verification — "Can we do no verification for now but
  accommodate at least account ownership verification in a future version?"; data — "Ongoing
  transactions for sure, then can we enrich the transaction data we have and add account balances
  (fresh balance checks or point-in-time snapshots, not sure which works better …)".

## Human tasks

Dashboard read 2026-11-14 (read-only). Nothing in the Plaid Dashboard needs changing for this
slice.

| Task | Why it matters | Where | State |
|------|----------------|-------|-------|
| Put the Sandbox `client_id` + Sandbox secret into the AWS secret the stack creates (owner does this; never pasted into chat, a file in the repo, or CDK) | Without it every Plaid call fails with invalid keys (GUIDE-001/021) | Keys: https://dashboard.plaid.com/developers/keys → AWS Secrets Manager, `ledgerly-dev` profile | needs_human (after the stack deploys) |
| Sandbox access to `transactions` | Required product | Dashboard → Products | verified (2026-11-14) |
| Webhook receiver | Item/transaction webhooks are set per Item in code, not here; webhooks are out of scope this slice (TASK-003) | — | not_applicable |
| Register an OAuth redirect URI | Chase connects by OAuth; without it Chase is silently absent or breaks mid-flow (OAUTH-001). Not needed for non-OAuth Sandbox banks | https://dashboard.plaid.com/developers/api | needs_human — before Production, not this slice (list is empty today) |
| Production prerequisites: company profile, data-security questionnaire (gates Chase) | Long lead time; cannot be read through the tools (TASK-006/009) | https://dashboard.plaid.com | cannot_verify — before Production |
| Confirm what Plaid bills for a Production `transactions` Item on this account | Dashboard shows Production authorized and **no trial products**; NFR-1.1 needs a number before any real Item | Dashboard → Settings → Team → Products / billing | needs_human — before Production |

## Implementation checklist

ADR-014 accepted 2026-11-15; backend build in progress.

- [ ] `adapters/plaid.py` — `/link/token/create`, `/item/public_token/exchange`,
      `/transactions/sync`, `/accounts/get`, `/item/remove`
- [ ] `core/plaid_normalize.py` + tests (sign flip TXN-005, null merchant TXN-013, pending flag)
- [ ] `api_plaid` Lambda + `plaid_sync` worker (full-loop sync, cursor saved last: TXN-002,
      TXN-007, TXN-011, DATA-007)
- [ ] `added` / `modified` / `removed` (TXN-004)
- [ ] Secrets Manager secrets + per-Lambda IAM; `dev` stage only
- [ ] SPA "Bank connection" panel (WEB-001/002/003, WEB-020/021)

## Acceptance

- Round 0: not run.

## Maintenance

This integration is maintained with the Plaid MCP; this file is its durable state. Agents working
in this repository: consult build_guidance before modifying any Plaid-touching code, and re-run
build_check_acceptance before reporting such a change as working. The acceptance above applies
only to the code as it was verified — later changes invalidate it.

## How to test

To be written with the code. Planned journey: sign in to the dev SPA → Bank connection → connect
First Platypus Bank with `user_good` / `pass_good` → transactions appear and categorize → Sync now
adds 0. Lifecycle: the `user_transactions_dynamic` test user (TXN-014).

## Decisions made

- 2026-11-15 (owner): ADR-014 accepted as written. Pending transactions count toward "spent".
  Route paths `/plaid/link-token`, `/plaid/exchange`, `/plaid/sync` stand (GUIDE-020).

## Open questions

- "Sync now" is a stated stopgap; moving to webhooks is a recorded follow-up (WEBHOOK-005).
