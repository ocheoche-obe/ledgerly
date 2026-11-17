# CLAUDE.md refresh, 2026-11-16

Notes on the rewrite of `CLAUDE.md` on branch `claude-md-refresh`. The old file is
`git show main:CLAUDE.md` (421 lines); the new one is about 180.

**One caveat on method.** The brief was to write the new file without opening the old one. The
harness loads `CLAUDE.md` into every session automatically, so the old text was in context from
the start. The new file was built from the code, docs, skills, workflows and git history, and
every claim in it was checked against one of those, but the first draft was not truly blind.

## How the new file was built

Read: `README.md`, `PLAID_PLAN.md`, the plan, ADL (index, ADR-014, ADR-015), backlog, the
architecture outline and change log, `.claude/` (skills, `/review-pr`, the `pr-reviewer` agent,
settings, the account hook), all four workflows and the `cdk-deploy` action, `infra/app.py`,
`infra/ledgerly/config.py`, `backend_asset.py`, `web.py`, the manifests, `ruff.toml`, and the
last 40 commits.

Ran locally: `pytest` (341 passed), `ruff check` (clean, ruff 0.16.2), `vitest` (32 passed).
Not run: `cdk synth`, and nothing against AWS (the SSO session was expired, and this session was
read-only on the cloud by instruction).

The test for each line was: would a capable new session get this wrong, or waste time, without
it? Things it can read off the code in a minute were left out.

## Carried over from the old file

These were in the old file and are kept, some reworded:

- **The merge rule ("Who merges")**: Claude merges after a blocker-free `/review-pr` on the final
  state plus green CI, and reports what the reviews found. The section keeps its name because
  `/review-pr` and `/wrap-slice` cite it.
- **What always waits for the owner**: data deletes, anything touching prod (including the
  `prod` environment approval), and owner decisions. "Ask when unclear" is kept.
- **Blind review after every PR**, with nothing but the PR number passed to the reviewer.
- The AWS account, region and profile rule, and why (shared SSO login).
- Infrastructure only through CDK; MCP and CLI for reads.
- Never read a secret value into context; Plaid's two secrets are the only runtime secrets.
- "Deployed is not working" and the Slice 5 story in one line.
- The Bedrock facts: inference-profile ids, which models this account can invoke, and that only
  invocation proves access.
- The core/adapters/functions seam, identity from the JWT only, ADR before code, diagram as code.
- The two Slice 6 traps: `cycleRef` and the `force` flag.
- The Plaid rules: Sandbox and `dev` only, Sandbox user, `accountType` sticky, loan rows excluded,
  owner signs in.
- The exact branch-deploy command and that the `cdk diff` is shown first.
- The inclusive, unvalidated 0.8 threshold ([B-8]).
- The cost ceiling, as a trigger for an ADR.

Added only after reading the old file (things the code did not reveal):

- The user-level MCP entry and the stale `agent-toolkit` AWS profile point at the other
  project's account, which is why the `.mcp.json` pin must stay.
- Hyphens, not em dashes, in AWS resource names.
- The Playwright version pin is deliberate, and its persistent profile holds real tokens.

## New in this version (not in the old file)

- Local venvs drift below their manifests ([B-9]); re-sync before trusting local gates.
- Build the SPA before `cdk synth`/`diff`/`deploy`, or the web deployment is `config.json` only.
- `BACKEND_ASSET_EXCLUDE` must list any new dot-directory in `backend/`.
- `ValueError` is the validation protocol (the reason TRY004 is off).
- Money sign convention, and Plaid's inverted sign.
- Use the Plaid MCP's `build_guidance` / `build_check_acceptance` (from `PLAID_PLAN.md`).
- Which docs are frozen, and that the architecture doc wins over the plan on design.
- One explicit line under "always waits": an owner instruction in the session not to merge.
  This states what was already implied; say if you would rather it not be there.

## Dropped, and why

| Dropped | Why |
|---|---|
| The per-file inventory of `backend/core`, `adapters`, `functions`, `infra`, `.github`, `frontend` (about 90 lines) | Readable from the tree and docstrings in a minute, and it goes stale every slice. It already listed no Plaid modules under `core/` or `adapters/`. |
| The "Architecture summary" | Duplicates the architecture doc and ADL index. |
| Slice-by-slice history (Slices 1 to 5, "Last completed", "Prior", "Earlier") | The plan owns it. The old file had two different "Last completed" entries. |
| Dev data counts as of 2026-08-07 (153 rows, 8 smoke rows, 0 budgets, cadence edit) | A three-month-old snapshot that Slice 9 changed; state like this belongs in the plan or is checked live. |
| Test counts | Stale on arrival (old file: 216 + 19; today: 341 + 32). |
| The list of 16 AWS skills in `~/.claude/skills/` and the remote catalog command | Machine-specific, and the session already lists available skills. |
| "Verify, don't guess" as a general instruction | A current model does this; the concrete Bedrock case is kept. |
| Playwright install steps and "what it is for" | Standard tool use. |
| The six-stage lifecycle description | `KICKOFF.md` and the plan cover it. |
| Detail of `/wrap-slice` steps (security review, code review, explain-diff rationale) | The skill holds it; the new file names the steps in one sentence. |
| Cognito logout parameters, `react-plaid-link` keyed-hook note | Now encoded in the code and its tests. |
| "A `!` command from another device is chat text" | A harness quirk, not project knowledge. |
| Budget alarm thresholds and expected monthly cost | In `infra/ledgerly/config.py` and ADR-014. |

## Things in the old file that looked wrong or out of date

1. **Slice 6 status contradicts itself and the repo.** The old file says "PR open, NOT yet
   verified live" and "Slice 6 is not done". PR #44 was merged. The plan's status board still
   shows 🔨 with no PR link, and every Slice 6 exit criterion is still unchecked. Whether the
   153 stranded transactions were ever recategorized is not recorded anywhere I could read.
   The new file flags this as open instead of guessing.
2. **Playwright headless.** One section says the server "runs `--headless`", another says it
   "runs headed (`.mcp.json`, local change)". The committed `.mcp.json` has `--headless`; your
   working tree has an uncommitted edit removing it. This branch does not touch that file.
3. **"Repository layout"** listed only `docs/`, `.claude/skills/`, `CLAUDE.md` and `KICKOFF.md`.
4. **"`.claude/skills/` — /start-slice and /wrap-slice"** omitted `.claude/commands/` and
   `.claude/agents/`, where `/review-pr` lives.
5. **"Deployment … Plaid live sync deferred"** in the opening paragraph, while Slice 9 had
   shipped Plaid Sandbox.
6. **The components section** predates Slice 9 for `core/` and `adapters/` (no `plaid_*`,
   `secrets.py`, `lambda_invoke.py`).

## Stale things outside CLAUDE.md (not changed here; this branch touches only CLAUDE.md and this file)

- `docs/ledgerly-plan.md`: Slice 6 on the status board (above); the Slice 3, 4 and 6 section
  headings still carry ⬜; the "Who merges" pointer in change log 1.4 is fine.
- `docs/ledgerly-backlog.md`: the index table stops at B-9, though B-10 and B-11 have entries.
- `docs/ledgerly-evaluation.md`: no entries for Slice 4 or Slice 6.
- `README.md`: says "CSV in v1" with no mention of Plaid, and shows a bare `cdk deploy` as the
  way to work, which ADR-011 and [B-10] have moved away from.
- `backend/eval/README.md`: its intro still frames the A/B as Opus 4.8 vs Sonnet 5; `run.py`
  uses Sonnet 4.6 vs Haiku 4.5.
- CI installs `aws-cdk@2` unpinned, while the local allow rule pins `2.1148.1`. [B-10] notes
  phantom diffs from CLI drift; pinning CI's CLI would close the same gap.
- `.claude/skills/wrap-slice` step 4 tells the agent to keep "Current build phase" compact. The
  old file had grown to about 120 lines there; the new one is back to a pointer.

## Not verified

- How `python3` resolves to the infra venv when the allowlisted deploy command runs. The new
  file states the requirement (cdk.json runs `python3 app.py`), not the mechanism.
- Anything about live `dev` state.

## Needs the owner's call

1. **Slice 6:** is it done? If the recategorize run and the budget entry happened, the plan
   should say so; if not, they are still owed before or alongside Slice 7.
2. **Should a PR that changes `CLAUDE.md`'s own merge or approval rules always wait for you?**
   Today such a PR is docs-only and would qualify for auto-merge under "Who merges". I did not
   add a rule, since that is your decision.
3. Whether to commit the headed-Playwright change in `.mcp.json` or keep it local.
