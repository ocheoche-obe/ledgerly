---
name: wrap-slice
description: End-of-slice checklist — verify tests and deployment, bring all canonical docs current (CLAUDE.md phase marker is blocking), commit, push, open the PR, and hand off cleanly.
---

# Wrap up a slice

Run these steps in order. The docs step is blocking: a slice is not done until the next
session can cold-start from `CLAUDE.md` alone.

## 1. Verify the work

- Unit tests green: `python -m pytest backend/tests -q`.
- If the slice changed deployed behavior, confirm it was actually deployed and smoke-tested
  end-to-end (real infra, not just unit tests). If smoke testing didn't happen, say so
  plainly — do not mark the slice complete.

## 2. Security review — the pre-commit gate (blocking — financial data)

Ledgerly handles banking/transaction/financial data, so a security review is part of the
definition of done for **every** slice, not an occasional pass. This runs **before the
commit in step 4** — it is the local pre-commit gate.

- Run the **`/security-review`** skill over the slice's diff.
- **Triage every finding.** Either fix it, or record an explicit, reasoned decision to
  accept/defer it (and route that to a follow-up slice or the parking lot in the plan doc).
  **Never commit with an unexplained finding** — an unaddressed finding blocks the commit.
- Re-check the standing invariants this project must never regress: identity only from the
  verified JWT, never the request payload (FR-1.3); no secrets in code/repo/logs (NFR-4.3);
  least-privilege IAM, no `*` on resources (NFR-4.4); encryption at rest + in transit;
  nothing sensitive logged. Note in the PR body that the review ran and how findings were
  resolved.

> **Defense in depth:** `/security-review` is the *local pre-commit gate*. CodeQL (SAST)
> and Dependabot (dependency updates) are the *remote net* — they re-scan every PR and on a
> weekly schedule (`.github/workflows/codeql.yml`, `.github/dependabot.yml`). Green locally
> is expected to stay green on the PR; if the remote net flags something new, triage it the
> same way before merge.

## 3. Bring the docs current (blocking)

- **`docs/ledgerly-plan.md`** — the linchpin. Flip the slice to ✅ on the status
  board (add the PR link once it exists), fill in its **Completion notes** (what shipped,
  what was deployed/verified, gotchas discovered, wrinkles deferred), check off exit
  criteria, and sanity-check that the *next* slice's section still reflects reality. This is
  what makes the next session's cold start cheap.
- **`CLAUDE.md` "Current build phase"** — refresh the pointer: current slice, last completed
  slice. It stays compact; detail belongs in the plan doc.
- **`docs/ledgerly-adl.md`** — every decision the slice forced is captured as an ADR
  (they should already exist from /start-slice step 6; verify). Update the index table and
  the "Last updated" line.
- **`docs/ledgerly-architecture.md`** — if implementation contradicted the doc,
  correct the doc (don't silently code around it — the contradiction should be explained),
  bump the version, add a change-log row.
- **`docs/ledgerly-evaluation.md`** — add the slice's evaluation beat (lifecycle
  stage 6): did it meet its exit criteria, what did it actually cost, what worked, what
  surprised us, and where each finding is routed (a requirement, an ADR, a future slice, or
  the parking lot).
- **Memory** — save durable gotchas (account-level constraints, API behaviors that
  contradict docs) that future sessions need; update the memory index.

## 4. Commit and push

- Commits follow a conventional style (`feat(infra):`, `fix(...):`, `docs:`, `test:`), each
  ending with the Co-Authored-By trailer.
- Logical commits: infra / backend / tests / docs separated where it's natural.
- Push the slice branch to origin.

## 5. Open the PR

```bash
gh pr create --base main
```

PR body: what the slice delivers, exit criteria and how each was verified (including
smoke-test evidence), decisions/ADRs added, doc corrections made.

## 6. Hand off

Tell the user, explicitly:

- PR URL and what's in it.
- That after they merge, the next `/start-slice` will fast-forward local `main`.
- Any threads deliberately left open, so they land in the next session's plan rather than
  being forgotten.

Do not merge the PR yourself; merging is the user's call.
