---
name: start-slice
description: Session-start ritual for beginning a new project slice — reconcile git, reload canonical context, verify cloud access, cut the branch, and agree exit criteria before any code is written.
---

# Start a new slice

Run these steps in order. Do not write code until step 6 is confirmed.

> SETUP NOTE: replace the `{{...}}` placeholders below (branch prefix, cloud profile,
> account/region, cost tool) once the project's stack and repo conventions are set — usually
> at the end of the first implementation slice. Delete this note afterwards.

## 1. Reconcile git

```bash
git fetch origin
git status -sb
```

- Local `main` must equal `origin/main`. If behind: `git checkout main && git merge --ff-only origin/main`. If it won't fast-forward, stop and show the user the divergence — never force anything.
- Working tree must be clean. If not, show the user what's dirty and ask before proceeding.
- Slice branches whose PRs are merged can be offered for local deletion (`git branch -d`), but only mention it — deletion is the user's call.

## 2. Reload canonical context

- Read **`docs/{{project-slug}}-plan.md`**: the status board (where are we) and the current
  slice's detail section (goal, scope in/out, ⚠ decisions, exit criteria). If the board
  disagrees with git history, the CLAUDE.md phase marker, or the deployed state, flag that
  before anything else.
- Read the ADRs and architecture-doc sections the slice's "Key refs" line names.
- Check memory for gotchas that apply.

## 3. Verify cloud access

```bash
{{e.g. AWS_PROFILE=<project>-dev aws sts get-caller-identity}}
```

Expected account: `{{account id}}`, region `{{region}}`. If the auth token is expired, ask
the user to re-authenticate — do not attempt to log in for them. Skip this step if the slice
involves no cloud calls yet.

## 4. Confirm cost posture

Only if paid cloud work is planned this session: sanity-check month-to-date spend is within
the {{$N}} ceiling. One line in the summary is enough.

## 5. Cut the branch

From up-to-date `main`:

```bash
git checkout -b {{branch-prefix e.g. feat/phase2-sliceN-short-kebab-name}}
```

## 6. Confirm scope and exit criteria — then stop

The plan doc's slice section already states scope, exit criteria, and ⚠ decisions. Before
writing code:

- Present them to the user, adjusted for anything learned since the roadmap was written. If
  scope changed materially, edit the plan doc's slice section so it stays authoritative.
- Resolve the slice's ⚠ decisions with the user. Per project convention, each decision not
  covered by the architecture doc becomes an ADR in `docs/{{project-slug}}-adl.md` *before*
  the code that implements it.
- Flip the slice's status to 🔨 on the plan doc's status board.

Wait for the user to confirm scope and exit criteria before implementation begins.
