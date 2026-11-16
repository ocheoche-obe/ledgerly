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
| Create the AWS secret `ledgerly/dev/plaid/api-keys` (us-east-1, account 816020558700) with value `{"client_id": "...", "secret": "<Sandbox secret>"}` (owner does this; never pasted into chat, a file in the repo, or CDK) | Without it every Plaid call fails with invalid keys (GUIDE-001/021) | Keys: https://dashboard.plaid.com/developers/keys → AWS Secrets Manager, `ledgerly-dev` profile | needs_human (can be done before or after the stack deploys) |
| Sandbox access to `transactions` | Required product | Dashboard → Products | verified (2026-11-14) |
| Webhook receiver | Item/transaction webhooks are set per Item in code, not here; webhooks are out of scope this slice (TASK-003) | — | not_applicable |
| Register an OAuth redirect URI | Chase connects by OAuth; without it Chase is silently absent or breaks mid-flow (OAUTH-001). Not needed for non-OAuth Sandbox banks | https://dashboard.plaid.com/developers/api | needs_human — before Production, not this slice (list is empty today) |
| Production prerequisites: company profile, data-security questionnaire (gates Chase) | Long lead time; cannot be read through the tools (TASK-006/009) | https://dashboard.plaid.com | cannot_verify — before Production |
| Confirm what Plaid bills for a Production `transactions` Item on this account | Dashboard shows Production authorized and **no trial products**; NFR-1.1 needs a number before any real Item | Dashboard → Settings → Team → Products / billing | needs_human — before Production |

## Implementation checklist

ADR-014 accepted 2026-11-15. Backend built 2026-11-15; not yet deployed or run against Sandbox.

- [x] `adapters/plaid.py` — `/link/token/create`, `/item/public_token/exchange`,
      `/transactions/sync`, `/accounts/get` (keys in headers GUIDE-001; errors carry code/type/
      request_id only GUIDE-006, ITEM-002; backoff + jitter ITEM-004/013; Sandbox host only)
- [x] `/item/remove` (disconnect, ITEM-005) — `DELETE /plaid/items/{itemId}`: Plaid first,
      then the token, then the record; transactions kept (PR #62)
- [x] `core/plaid_normalize.py` + tests (sign flip TXN-005, null merchant TXN-013, pending flag)
- [x] `core/plaid_sync.py` + `plaid_sync` worker (buffer all pages, restart from the starting
      cursor on mutation, count 500, cursor saved last: TXN-002, TXN-007, TXN-011, DATA-007 —
      DATA-007's "one transaction" is met by idempotent writes + cursor-last, since a first sync
      exceeds DynamoDB's transaction size)
- [x] `added` / `modified` / `removed`, pending merged into posted via
      `pending_transaction_id` with the category carried over (TXN-004)
- [x] `api_plaid` Lambda: link token (CONV-001/002), exchange (GUIDE-015, duplicate-institution
      guard ITEM-011), sync start
- [x] Secrets Manager + per-Lambda IAM; `dev` stage only (`prod` synth has no Plaid resources)
- [x] Sandbox test actions (direct Lambda invoke only, refused outside Sandbox):
      `sandbox_link` (SANDBOX-003) and `sandbox_refresh` (TXN-014). `/transactions/refresh` is a
      billed add-on in Production (GUIDE-016) and is reachable only through that test action.
- [x] SPA "Bank connections" panel (WEB-001/002/003, WEB-020/021): pre-initialized Link,
      Sync now, update-mode Reconnect on `ITEM_LOGIN_REQUIRED`, Disconnect (PR #62)
- [x] Loan accounts left out of the dashboard figures (owner decision below)
- [x] Dev-only Cognito Sandbox test user `PlaidSandboxUser` (owner decision below)
- [ ] Deployed to dev and run live (blocked on the owner's `cdk deploy`)

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
- 2026-11-15 (owner): **Loan payments are transfers, not spend.** Accounts of Plaid type `loan`
  are left out of every dashboard figure (`summarize(excluded_account_ids=...)`); the dashboard
  says how many rows it left out, and loan balances stay on Bank connections. A "Transfer"
  category for card payments etc. waits for Slice 7.
- 2026-11-15 (owner): **Sandbox data lives under its own Cognito user** (`PlaidSandboxUser`,
  dev only, a `+sandbox` plus-address of the owner's email), isolated by the `USER#<sub>`
  partition (ADR-006). The Sandbox rows already in the owner's partition are deleted with
  `backend/ops/purge_plaid_sandbox.py` — approved, but **not before the deploy is done and the
  live checks are ready** (owner's condition).
- Proposed, owner to confirm: new route paths `GET /plaid/items`,
  `DELETE /plaid/items/{itemId}`, and `POST /plaid/link-token {itemId}` for update mode.

## Runbook: move Sandbox off the owner's partition (owner-approved, not yet run)

Dry run 2026-11-15 (read-only) on the owner's partition: **701 items** selected — 349 Sandbox
transactions, 349 `PLAIDTXN#` pointers, 3 Plaid sync imports, dated 2026-08-21 → 2026-11-15;
0 Plaid-looking items left alone. Kept: 153 Chase CSV rows (Jun–Jul), 8 Slice-5 smoke rows
(Aug), 15 categories, 4 CSV imports, the profile. PITR is enabled (35 days) and is the undo.

1. Owner: deploy `Ledgerly-dev` from the PR branch. This creates the Sandbox user; Cognito
   emails its temporary password to the `+sandbox` address.
2. Logged in as the owner, **Disconnect** First Platypus Bank in the new panel (live test of
   `/item/remove`). The purge refuses to run while any connection is still linked.
3. Dry run: `cd backend && AWS_PROFILE=ledgerly-dev .venv/bin/python -m ops.purge_plaid_sandbox
   --sub <owner sub>`. Expect 701; anything else is a reason to stop and look.
4. Execute: same command plus `--execute --expect 701`. It writes a JSON manifest of every item
   first, deletes, then re-plans to confirm 0 remain.
5. Owner logs in once as the Sandbox user (sets its password; Claude never sees it). Live test
   there: connect First Platypus as `user_transactions_dynamic` and a second institution as
   `user_good` (it has the loan accounts), Sync now, Reconnect via the `sandbox_reset_login`
   invoke, Disconnect, and check that the dashboard leaves loan rows out.
6. `build_check_acceptance`, then `/wrap-slice`.

## Open questions

- "Sync now" is a stated stopgap; moving to webhooks is a recorded follow-up (WEBHOOK-005).
