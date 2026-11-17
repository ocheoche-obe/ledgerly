# Review checklist: Ledgerly

Read by the harness reviewer (`/harness:review-pr`) **from the PR's base branch**, so a change to
this file takes effect only after it merges. Everything Ledgerly-specific that the reviewer checks
lives here; the harness supplies the procedure, the generic checks and the report format.

## Automated checks

Run from the repo root. These are the gates CI runs. A failing check is a blocker.

1. `ruff check backend infra`
2. `(cd backend && python3 -m pytest -q)`. Use `python3`: CI's `python` is not on PATH on the review host.
3. `(cd frontend && npm ci --no-audit --no-fund && npm run build && npm test)`.
   Report the frontend build and vitest separately, with vitest's pass count.
4. `(cd infra && cdk synth --all -q && python check_prod_has_no_plaid.py)`. **Only if the diff
   touches `infra/` and `cdk` is installed**; otherwise mark it not run and say why. Skipping it
   for a diff that does not touch `infra/` does not make the verdict inconclusive.

## Docs to read

`CLAUDE.md` (conventions, invariants), then only the sections the diff touches of
`docs/ledgerly-architecture.md`, `docs/ledgerly-adl.md` (ADRs) and `docs/ledgerly-plan.md`.

## Domain checks

- **Secrets.** Plaid `access_token` never leaves the server; the browser only ever holds a
  `link_token` (in flight) and a `public_token` (in transit). No key, token or secret in code,
  tests, fixtures, logs, API responses, DynamoDB table items, CDK, or the client bundle.
- **Auth.** Every new route sits behind the JWT authorizer. User identity comes only from the
  verified JWT claims, never from the body, path or query (FR-1.3). Every DynamoDB key and every
  Secrets Manager lookup is scoped by that `sub`. Check for IDOR: an `itemId` or `importId` from
  the request used without the caller's partition.
- **Data integrity.** Money is integer cents with the documented sign convention. Writes that must
  be atomic are; idempotency and replay are safe; nothing deletes owner data without an explicit
  owner action; partial failures leave a state the next run can recover from.
- **IAM and infra.** Least privilege, no `*` resources, new permissions scoped to one resource;
  `prod` still synthesizes with no Plaid resources; no infrastructure created outside CDK.
- **Plaid API use.** Errors branched on `error_code` / `error_type`, not message text or HTTP
  status; single-use tokens never retried; removing a connection calls Plaid's remove endpoint
  rather than only deleting our record.
- **Frontend.** No secret material in state or `localStorage`; error and loading paths are
  handled; nothing renders unescaped HTML from API data.
- **Tests.** New behaviour has tests, including the failure branches; tests assert outcomes, not
  just that mocks were called.

## Extra hard rules

- AWS context is describe/list only, and always with `AWS_PROFILE=ledgerly-dev`. No `cdk deploy`,
  no AWS write calls, never `GetSecretValue`.
- Install frontend dependencies with `npm ci` only; `npm install` rewrites the lockfile.

## Merge rule

Unchanged by this file. See "Who merges" in `CLAUDE.md`, including the cases that always wait for
the owner.
