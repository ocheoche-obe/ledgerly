---
name: start-slice
description: Session-start ritual for beginning a new project slice — reconcile git, reload canonical context, verify cloud access, cut the branch, and agree exit criteria before any code is written.
---

# Start a new slice

Run these steps in order. Do not write code until step 7 is confirmed.

## 1. Reconcile git

```bash
git fetch origin
git status -sb
```

- Local `main` must equal `origin/main`. If behind: `git checkout main && git merge --ff-only origin/main`. If it won't fast-forward, stop and show the user the divergence — never force anything.
- Working tree must be clean. If not, show the user what's dirty and ask before proceeding.
- Slice branches whose PRs are merged can be offered for local deletion (`git branch -d`), but only mention it — deletion is the user's call.

## 2. Sweep Dependabot PRs

Dependency PRs are handled here — at slice start, in one batch — not ad hoc mid-slice.
(Dependabot runs monthly per `.github/dependabot.yml`; security PRs can appear anytime.)

```bash
gh pr list --author app/dependabot --state open
```

- **Grouped minor/patch PRs with green CI** → merge them (with the user's go-ahead),
  then re-sync local `main` before cutting the branch.
- **Major-version PRs** → a deliberate decision with the user: schedule as an upgrade
  task, or close with a comment saying why and when it will be revisited. Never merge a
  major just because CI is green — the frontend test gate is thin (see plan doc, Slice 2).
- **Red CI on a dependency PR** → read the failure before touching anything; peer-conflict
  failures usually mean interdependent packages split across PRs (fix the grouping in
  `dependabot.yml` rather than force-merging).
- **Security-update PRs** → highest priority in the sweep; if one is sitting open, deal
  with it before anything else in the slice.

## 3. Reload canonical context

- Read **`docs/ledgerly-plan.md`**: the status board (where are we) and the current
  slice's detail section (goal, scope in/out, ⚠ decisions, exit criteria). If the board
  disagrees with git history, the CLAUDE.md phase marker, or the deployed state, flag that
  before anything else.
- Read the ADRs and architecture-doc sections the slice's "Key refs" line names.
- Check memory for gotchas that apply.

## 4. Verify cloud access — hard account assertion

Skip only if the slice makes no cloud calls at all. Otherwise this is a **hard gate**: no
`cdk`, `aws`, or any account-mutating command runs until it passes. Run the shared guard
(the same script the SessionStart hook uses — one source of truth):

```bash
.claude/check-aws-profile.sh
```

- **Expected: `✓ OK` → account `816020558700`** (Ledgerly, ADR-010), region `us-east-1`,
  profile `ledgerly-dev`. Ledgerly always uses `ledgerly-dev` — never a bare/default
  profile, never `careervault-dev` (`768396678224`, a different project on the same SSO).
- **`✗ MISMATCH` → STOP.** Do not run another cloud command; you are pointed at the wrong
  account. Surface it to the user. (Deploys are also pinned in `infra/app.py`, so a
  wrong-account `cdk deploy` fails fast — but never rely on that alone.)
- **`⚠ not authenticated` →** ask the user to run `aws sso login --profile ledgerly-dev`
  — never log in for them — then re-run the guard.
- Every AWS/CDK command this session carries `--profile ledgerly-dev` (or
  `AWS_PROFILE=ledgerly-dev`); never a default profile.

## 5. Confirm cost posture

Only if paid cloud work is planned this session: sanity-check month-to-date spend is within
the **$10/month** ceiling (NFR-1.1). Because Ledgerly has its own account (ADR-010), the
account's month-to-date bill *is* Ledgerly's spend. One line in the summary is enough.

## 6. Cut the branch

From up-to-date `main`:

```bash
git checkout -b feat/sliceN-short-kebab-name   # e.g. feat/slice1-walking-skeleton
```

## 7. Confirm scope and exit criteria — then stop

The plan doc's slice section already states scope, exit criteria, and ⚠ decisions. Before
writing code:

- Present them to the user, adjusted for anything learned since the roadmap was written. If
  scope changed materially, edit the plan doc's slice section so it stays authoritative.
- Resolve the slice's ⚠ decisions with the user. Per project convention, each decision not
  covered by the architecture doc becomes an ADR in `docs/ledgerly-adl.md` *before*
  the code that implements it.
- Flip the slice's status to 🔨 on the plan doc's status board.

Wait for the user to confirm scope and exit criteria before implementation begins.
