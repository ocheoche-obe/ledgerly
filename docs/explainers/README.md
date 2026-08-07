# Explainers

Interactive HTML walkthroughs of merged changes — one per significant PR, named
`YYYY-MM-DD-<slug>.html`.

Each has four parts: **Background** (the system the change lands in, with a skippable
deep-dive on the underlying AWS/LLM machinery), **Intuition** (the essence, with toy data
and diagrams), **Code walkthrough**, and a five-question **Quiz** with per-option feedback.

Open one directly in a browser — they're self-contained, no build step and no network access.

## Why these exist

Ledgerly is an explicit learning vehicle, and most of its code is agent-generated. These
close the gap between "CI went green" and the owner actually understanding what is deployed.
They are a *record*, not documentation: an explainer describes one change at one moment.
For current truth, always read the canonical docs (`ledgerly-architecture.md`,
`ledgerly-adl.md`, `ledgerly-plan.md`) — an explainer is never authoritative and is not
updated once written.

## Generating one

Via the `explain-diff` skill (also step 7 of `/wrap-slice`):

```bash
python3 .claude/skills/explain-diff/render.py <spec.json>
```

See `.claude/skills/explain-diff/SKILL.md` for the writing brief and `render.py --help`
for the JSON spec schema.
