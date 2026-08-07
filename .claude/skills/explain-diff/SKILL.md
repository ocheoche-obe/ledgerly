---
name: explain-diff
description: Turn a PR, branch, or diff into a rich interactive HTML explainer — background, intuition, code walkthrough, and a five-question quiz — written so the owner genuinely understands the code that was generated and deployed. Use when asked to explain a PR/diff/branch/slice, or as the advisory step 7 of /wrap-slice.
---

# Explain a diff

Produce a rich, interactive explanation of a code change, rendered to
`docs/explainers/YYYY-MM-DD-<slug>.html` via the bundled `render.py`.

> Adapted for Ledgerly from Geoffrey Litt's explain-diff recipe (via
> [this gist](https://gist.github.com/ankitg12/8e808d387799de4e9839bc393f8e6405)).
> The upstream also has a Notion variant; Ledgerly uses the HTML one — there's no
> Notion MCP here, and a git-tracked file keeps each explainer next to the code it explains.

## Why this exists in *this* project

Ledgerly has a stated secondary purpose: it is **an explicit learning vehicle** for AI/LLM
pipelines, AWS serverless, IaC/CI-CD, and full-stack work. Most of the code is agent-generated.
An explainer is how the owner converts "Claude built it and CI went green" into
"I understand what is running in my account and why."

Treat that as the success criterion. The reader is the **sole owner-developer**: strong on
intent and product judgment, deliberately using this project to build depth in AWS, LLM
pipelines, and IaC. They are not a stranger to the codebase — they wrote the requirements and
approved every ADR — so don't re-explain what Ledgerly *is*. Do explain the machinery.

## Step 1 — Get the diff and its context

Work out what's being explained. In rough order of preference:

```bash
gh pr diff <N>                       # a specific PR (best — has the description too)
gh pr view <N> --json title,body,files
git diff main...HEAD                 # the current slice branch
git diff <base>..<head>              # an explicit range
```

Also pull the surrounding context, because Background is the section that most often comes out
thin:

- **`docs/ledgerly-architecture.md`** — the design the change fits into (§ numbers are worth citing).
- **`docs/ledgerly-adl.md`** — the *why*. If the diff touches an ADR'd decision, name the ADR.
- **`docs/ledgerly-plan.md`** — which slice this is, and its exit criteria.
- The files *around* the diff, not just the changed lines. Read the module the change lands in.

Never explain a diff from the patch alone. A hunk that adds three lines to
`adapters/dynamo.py` means nothing without the single-table access patterns it serves.

## Step 2 — Write the four sections

**Background.** Explain the existing system the change lands in. Two layers, explicitly
labelled so the reader can skip the first:

- A *deep* background for the underlying technology — DynamoDB single-table design, SQS
  visibility timeouts and partial batch failure, Bedrock forced-tool structured output,
  presigned S3 PUTs, CDK constructs. This is the layer worth real investment; it is the
  learning-vehicle payload. Mark it clearly skippable.
- A *narrow* background on the specific Ledgerly code being modified.

**Intuition.** The essence, not the details. Use concrete toy data — a single Chase row,
one `USER#<sub>` partition, one SQS message. Diagrams liberally. If the reader reads only
this section, they should still get the core idea.

**Code walkthrough.** High-level, grouped so it reads in a sensible order — typically
`core/` → `adapters/` → `functions/` → `infra/` → `frontend/`, which mirrors Ledgerly's
portability seam and is usually also the dependency order. Group by *idea*, not by file
alphabetical order. Skip noise (lockfiles, formatting).

**Quiz.** Five multiple-choice questions, medium difficulty — hard enough that you must have
understood the substance to answer, but never gotchas. Test the *reasoning*, not trivia like
"what line number changed".

Give every option an `explanation` saying why it's right or wrong. That's the whole learning
payload of the quiz, and it's the main thing this renderer adds over the upstream gist.

Write the explanation as **the reason only** — the renderer already prefixes "✅ Correct." or
"❌ Not quite.", so an explanation starting with "Correct —" or "Wrong —" renders as a stutter
("✅ Correct. Correct — …"). Start with the substance: *"the natural key already matches, so
`put_transaction` is a no-op."*

## Step 3 — Render

Write a JSON content spec and render it. **Do not hand-write the HTML page** — the CSS, quiz
JS, table of contents, option shuffling, and filename convention are all handled:

```bash
python3 .claude/skills/explain-diff/render.py /path/to/spec.json
```

It prints the output path. Run with `--help` for the exact schema. Notes:

- Section `html` fields are **raw HTML you write directly**. Use `<pre>` for code (already
  `white-space: pre-wrap`), `.diagram` / `.flow` / `.box` / `.box.fail` for flow diagrams,
  `.callout` for definitions and edge cases, plain `<table>` for comparisons.
- Quiz option `text` and `explanation` are **plain text and get escaped** — write `cents < 0`
  freely, but don't put `<code>` tags in them, they'll render literally.
- Options are shuffled at render time. Write them in whatever order reads naturally.
- Keep the spec in the scratchpad, not the repo — the rendered HTML is the artifact worth
  keeping, not the intermediate JSON.

## Step 4 — Commit it

The explainer is a project record, so it lands with the work:

```bash
git add docs/explainers/<file>.html
```

Mention the path in the PR body or the handoff so the owner can find it.

## Writing style

Write with the clarity and flow of Martin Kleppmann — engaging, classic style, smooth
transitions between sections rather than four disconnected essays. Prose that explains, not
bullet-soup that lists.

**Diagram families.** Pick a small number and reuse them throughout, with example data:

- **Pipeline flow** — the Ledgerly spine: `CSV → S3 → importer → SQS → categorizer → DynamoDB`.
  Use `.flow` with `.box`, and `.box.fail` for the DLQ / error path. Show a real row moving
  through it.
- **Item shape** — DynamoDB keys as a small table: `PK`/`SK`/`GSI1PK` with actual values like
  `USER#abc` / `TXN#01J...`. This makes access-pattern changes legible.
- **UI sketch** — a simplified version of the panel the owner sees (`TransactionsPanel`,
  `ImportPanel`, the Slice 6 dashboard) when the change is user-visible.

No ASCII diagrams — use the renderer's HTML classes.

## Ledgerly-specific things worth flagging when relevant

If the diff touches these, the explainer should say so — they're the project's hard-won lessons:

- **Deployed ≠ working.** If the change has live behaviour, say what still needs verifying
  against the deployed stack. Slice 5 sat broken for 12 days behind a green pipeline.
- **Idempotency.** Three levels — file hash, row natural key (ADR-012, includes `balanceCents`),
  S3 redelivery. Changes near the importer almost always interact with one of them.
- **Un-filed, never mis-filed** (FR-3.5). The categorizer leaves rows Uncategorized rather than
  guessing wrong. Confidence threshold is `0.8` and **inclusive** (`>=`).
- **The portability seam.** `core/` has no AWS imports; boto3 lives in `adapters/`; handlers stay
  thin. If a diff crosses that line, it's worth explaining why.
- **Cost.** $10/month ceiling (NFR-1.1). Anything adding Bedrock calls or storage deserves a note.
