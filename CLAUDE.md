# Ledgerly

Single-user personal budgeting app, and the owner's deliberate learning project for LLM
pipelines, AWS serverless and IaC. Bank transactions come in by CSV upload or Plaid (Sandbox
only), an LLM files each one into an owner-defined category, and a dashboard shows budget vs.
actual per category per budget cycle.

Most code here is agent-written and the owner reads it to learn. Explain non-obvious choices,
and when live cloud behaviour contradicts a doc, say so and correct the doc.

## Source of truth

`docs/` is canonical and each file owns one question. Read the relevant one before deciding
anything; this file only points.

| File | Owns |
|---|---|
| `docs/ledgerly-plan.md` | **When**: slice order, scope, exit criteria, status board, completion notes |
| `docs/ledgerly-architecture.md` | **How/where**: design, data model (§2), access patterns and routes (§2.5), sequences (§3). Wins over the plan on design |
| `docs/ledgerly-adl.md` | **Why**: ADR-001…015. Append-only, never renumbered |
| `docs/ledgerly-requirements.md` | **What**: the FR-/NFR- numbers cited everywhere |
| `docs/ledgerly-backlog.md` | Build-time observations `[B-n]` awaiting triage. Post-MVP features go in the plan's parking lot instead |
| `docs/ledgerly-evaluation.md` | Per-slice retrospectives |
| `PLAID_PLAN.md` | Plaid build-kit state: human tasks, acceptance, how to test |

`KICKOFF.md` and `docs/ledgerly-reference.md` are frozen; leave them alone.
`docs/explainers/*.html` are records of one change, never authoritative.

**ADR before code.** A decision the architecture doc doesn't cover is written into the ADL, and
agreed with the owner, before the code that implements it. New paid services, new secrets and
anything touching the cost ceiling ($10/month, NFR-1.1) always qualify.

## Layout rules

- `backend/core/` is pure domain logic with **no AWS imports**. boto3 and outbound HTTP live in
  `backend/adapters/`. `backend/functions/*/handler.py` stay thin.
- `backend/eval/` and `backend/ops/` are owner-run tools, not Lambdas.
- `infra/` is CDK in Python: `Ledgerly-dev` and `Ledgerly-prod` (one account, constructs in
  `infra/ledgerly/constructs/`), plus `Ledgerly-cicd` (GitHub OIDC role, deployed once by hand).
  Per-stage knobs and the Bedrock model id live in `infra/ledgerly/config.py`.
- `frontend/` is a React + Vite + TypeScript SPA. Only `DashboardPanel` has a real stylesheet;
  the other panels use inline styles until [B-3].

## Build and test

```bash
cd backend  && .venv/bin/python -m pytest          # moto-backed; no AWS needed
.venv/bin/ruff check . ../infra                    # from backend/ (CI: `ruff check backend infra`)
cd frontend && npm ci && npm run build && npm test # build includes tsc; tests are vitest
cd infra    && cdk synth --all && python check_prod_has_no_plaid.py   # infra/.venv active
```

- **Local venvs drift below their manifests** ([B-9]), which has produced green local gates that
  CI rejected. Run `pip install -r` (`backend/requirements-dev.txt`, `infra/requirements.txt`)
  before trusting a local result.
- CI uses Python 3.13 and Node 22. Local Node is newer, so set
  `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1` for cdk.
- **Build the SPA before any `cdk synth`/`diff`/`deploy`.** Without `frontend/dist` the web
  deployment contains only `config.json`.
- Lambdas have **zero third-party runtime dependencies**: the asset is the `backend/` tree with
  no pip step. So Bedrock is called with boto3 `invoke_model` (not the `anthropic` SDK) and Plaid
  with stdlib `urllib`. A new tool that writes a dot-directory into `backend/` must be added to
  `BACKEND_ASSET_EXCLUDE` (`infra/ledgerly/backend_asset.py`); CDK does not read `.gitignore`.
- The SPA fetches `/config.json` at runtime, which exists only in the deployed bucket, so
  `npm run dev` has no backend unless you supply one. The dev Cognito client accepts
  `http://localhost:5173/` as a callback; prod does not.

## AWS and deploying

- Account `816020558700`, region `us-east-1`, profile `ledgerly-dev`. **Every AWS/CDK command
  carries `AWS_PROFILE=ledgerly-dev` or `--profile ledgerly-dev`.** The same SSO login reaches
  another project's account, so a default profile can hit the wrong one. A SessionStart hook
  reports the account, and `infra/app.py` pins it. If the hook says not authenticated, ask the
  owner to run `aws sso login --profile ledgerly-dev`.
- **Normal path:** merging to `main` runs `deploy.yml`: checks, then `dev` deploys, then `prod`
  waits for the owner's approval of the GitHub `prod` environment. Pushes that touch only docs,
  `*.md`, `.claude/**`, `.gitignore` or `.mcp.json` don't deploy. `main` is not branch-protected.
- **Deploying `dev` from a branch** (to verify before merge): from `infra/`, with the SPA built
  and `python3` resolving to the infra venv, show the owner `cdk diff Ledgerly-dev` first, then
  run exactly
  `npx --yes aws-cdk@2.1148.1 deploy Ledgerly-dev --profile ledgerly-dev --require-approval never`.
  The owner's machine allowlists that exact string; [B-10] will replace it with a GitHub Action.
- **All infrastructure changes go through `infra/`.** The CLI and the `aws-mcp` server
  (`.mcp.json`, profile-pinned) are for reads and diagnosis only. Never remove that pin: the
  owner's user-level MCP entry and a stale `agent-toolkit` AWS profile point at the other
  project's account.
- Use hyphens, not em dashes, in AWS resource names and descriptions.
- **Never read a secret value into context**: no `GetSecretValue`, no printing `.env`. The only
  runtime secrets are the two Plaid ones in Secrets Manager. Describing a secret is fine.
- **Deployed is not working.** A slice with live exit criteria is done only when someone has run
  them against the deployed stack. Slice 5 sat "deployed" and broken for 12 days.
- Bedrock: models are inference-profile only (`us.anthropic.…` ids; IAM needs the profile and
  the foundation-model ARNs). This account can invoke Haiku 4.5, Sonnet 4.5 and Sonnet 4.6, and
  is denied newer models regardless of model agreements. The availability API reported a denied
  model as available, so **only a real invocation proves access**.

## Workflow

Work happens in slices: `/start-slice` (git reconcile, Dependabot sweep, account check, agree
scope and exit criteria before coding) and `/wrap-slice` (verify live, `/security-review` as a
blocking gate, `/code-review medium` as advisory, bring docs current, PR, `explain-diff`, blind
review, merge, hand off). The skills in `.claude/skills/` hold the detail.

**Blind review after every PR.** After opening any PR, slice or cleanup, run
`/harness:review-pr`, and again on the final commit before merging. It reviews in a fresh,
read-only subagent (`harness:pr-reviewer`) that has not seen the building conversation and gets no
summary of the work. It applies `.claude/review-checklist.md` as it stands on the base branch and
returns blocker, should-fix and nit findings with file:line, plus a **pass**, **fail** or
**inconclusive** verdict bound to the commit it judged. A verdict covers only that commit. Fix
every blocker and triage every should-fix. It complements `/code-review` and `/security-review`;
it doesn't replace them.

**Requires the `harness` plugin.** `/harness:review-pr` and `harness:pr-reviewer` come from it. If
they are not available in a session, do not substitute another review and do not merge: stop and
ask the owner.

### Who merges

Owner decision, 2026-11-16; pass required since 2026-11-20. Claude merges a PR
(`gh pr merge <n> --squash --delete-branch`) only when both hold on the PR's **final** commit,
after doc updates:

1. `/harness:review-pr` returns **pass** for that exact commit, and
2. CI is green on that same commit.

A **fail** or **inconclusive** verdict never merges without the owner; "no blockers" is not
enough. Inconclusive means a check did not run, the commit could not be confirmed or the diff was
not fully read. Claude may fix the cause, push, let CI re-run and re-run `/harness:review-pr` on
the new commit; only a pass on the final commit, with CI green, lets Claude merge. Otherwise stop
and ask the owner. Afterwards tell the owner what each review found, how blockers and
should-fixes were handled, and what was merged.

**Always waits for the owner, whatever the review and CI say:**

- anything that **deletes data**,
- anything that **touches prod**, including approving the `prod` environment gate (merging
  deploys `dev` only),
- anything needing an **owner decision**: product behaviour, cost, scope, an ADR choice,
- an instruction from the owner in the session not to merge.

If it isn't obvious which side a PR falls on, ask.

## Invariants and traps

- **Identity comes only from verified JWT claims** (FR-1.3), never from body, path or query.
  Every DynamoDB key and secret lookup is scoped by that `sub` (`USER#<sub>` partition, ADR-006).
- **Validation failures raise `ValueError`**, which handlers map to 400. A `TypeError` would
  escape as a 500, which is why ruff's TRY004 is switched off.
- Money is integer cents, negative = money out. Plaid's sign is the opposite and is flipped on
  the way in.
- **Cycles are addressed in URLs by `current` or an ISO date inside the cycle**, never the raw
  ID (`M#2026-07`, `B#2026-07-10`). The server derives the ID from the cadence history.
- **The categorizer skips anything not `uncategorized`**; that is what makes SQS redelivery
  free. Re-running over categorized rows therefore needs the `force` flag carried in the
  message, not a filter where messages are enqueued. Owner-confirmed and corrected rows are
  never overwritten.
- CSV rows dedupe on a content hash that includes the running balance (ADR-012). Re-uploading a
  file adds nothing and enqueues nothing.
- Dashboard arithmetic lives in `core/budgets.summarize` and its semantics are pinned by tests:
  spend is the negated net, unfiled money shows as a synthetic Uncategorized row, `remaining`
  counts only budgeted categories, and clearing a budget deletes the item.
- The 0.8 confidence threshold is inclusive and has not been validated beyond an 8-row smoke
  set ([B-8]). Settle both when Slice 7 sizes the review queue.
- Re-render the architecture diagram (`docs/render_architecture.py`, `render-diagram` skill) in
  the same commit as any change to the system's shape.

## Plaid (ADR-014, ADR-015)

- **Sandbox only, `dev` only.** `prod` must synthesize with no Plaid resources, and CI checks
  it. Plaid Production needs its own ADR with verified pricing first.
- Use the `plaid` MCP server: call `build_guidance` before changing Plaid-touching code and
  `build_check_acceptance` before reporting such a change as working. The recorded acceptance
  covers only the code as it was verified.
- **Test as the dev Sandbox Cognito user, never the owner's account.** Nothing enforces this
  ([B-11]). If Sandbox rows land in the owner's partition, `backend/ops/purge_plaid_sandbox.py`
  removes them; it deletes data, so the owner runs or approves it.
- The Plaid `access_token` never leaves the server or reaches a log, API response or table item.
- Rows from `loan` accounts are left out of every dashboard figure. `accountType` is stamped at
  sync and updates must never remove it.
- Browser checks use the Playwright MCP (`@playwright/mcp` is pinned on purpose; it is a
  `0.0.x` package). The owner signs in; Claude never types a password. Its browser profile
  persists, so real Cognito tokens sit on disk: don't point it at prod casually. Test steps are
  in `PLAID_PLAN.md` under "How to test".

## Current build phase

Keep this section to a pointer; detail belongs in the plan.

- **Last completed:** Slice 9, Plaid Sandbox ingest (#61, #62), verified live on `dev`
  2026-11-16.
- **Next:** Slice 7, review queue and corrections, plus the **Transfer category** (transfers
  between the owner's own accounts still count as spend).
- **Open:** Slice 6 (budgets and dashboard) merged as #44, but the plan still shows it in
  progress with its live exit criteria unchecked. Verify against `dev`, or ask the owner, before
  treating it as done.
