---
description: Blind, read-only review of the current PR in a fresh subagent — secrets, auth, data integrity, IAM, tests — ranked findings and a merge verdict.
argument-hint: "[PR number — defaults to the current branch's PR]"
---

Run a blind review of a pull request. The review must come from a **fresh subagent that has
not seen this conversation**, so it judges the change on its own and isn't anchored by how it
was built.

1. Resolve the PR. If `$ARGUMENTS` is a number use it; otherwise run
   `gh pr view --json number,title,headRefName` for the current branch. If there is no PR,
   stop and say so — don't review an unpushed branch.
2. Launch **one** subagent with the Agent tool:
   - `subagent_type: "pr-reviewer"` (defined in `.claude/agents/pr-reviewer.md`, read-only:
     Read/Grep/Glob/Bash). If that agent type isn't available in this session (agents are
     loaded at session start), use `general-purpose` and paste the full body of
     `.claude/agents/pr-reviewer.md` into the prompt as its instructions.
   - The prompt contains **only**: the PR number, its head branch, and "Review this PR
     following your instructions." Do **not** pass any summary of the work, the intent, known
     issues, or what you think is risky — that is exactly the context a blind review must not
     have.
3. When it returns, relay its report to the owner verbatim (it is already in the
   blocker / should-fix / nit format with file:line and a one-line verdict).
4. Then, separately and clearly marked as your own view, triage each blocker and should-fix:
   real, false positive (with the reason), or already known. Don't silently drop any.

Do not fix anything as part of this command. Fixing blockers is the caller's next step, and
CLAUDE.md says the owner hears what the review found before being asked to merge.
