# Project Starter Kit — Agentic Engineering Framework

> A reusable framework for kicking off a new project the same disciplined way
> **CareerVault** was run: a full delivery lifecycle (requirements → architecture →
> implementation → testing → deployment → evaluation, then *loop*), a doc set where every
> document answers exactly one of the six questions (**who / what / where / how / why /
> when**), and two session rituals that keep every session cheap to start and finish.
>
> This kit is **generic and stack-open**. Nothing about any specific project — or any
> specific cloud — is baked in. You carry it into a fresh Claude session, name your
> project, and Claude interviews you and fills the skeletons with you, one document at a
> time.

---

## Vibe coding vs. agentic engineering — what this kit is for

There's a spectrum in how people build with coding agents:

- **Vibe coding** — talk to the agent, get a prototype fast. Great for spikes, demos, and
  "will this even work?" No lasting structure; the reasoning lives only in the chat.
- **Agentic engineering** — the agent operates inside a real engineering system:
  requirements are gathered, architecture is designed, decisions are recorded, work is
  sliced and tested and deployed, and results are *evaluated* to drive the next cycle. This
  is what builds things that last.

**This kit is built for the agentic-engineering end — but it flexes.** For a quick spike,
you can skip straight to a thin slice. For something you want to keep, run the full cycle.
The structure is the same either way; you choose how much of it to use.

---

## The two ideas this kit is built on

### Idea 1 — The delivery lifecycle is a *cycle*, not a line

Every project (and every version of it) moves through six stages, then feeds back into
itself:

```
      ┌──────────────────────────── findings feed the next version ───────────────────────┐
      │                                                                                    │
      ↓                                                                                    │
 1. REQUIREMENTS → 2. ARCHITECTURE → 3. IMPLEMENTATION → 4. TESTING → 5. DEPLOYMENT → 6. EVALUATION
   (what/who)        (how/where)       (build in            (verify)     (ship)         (measure what
                                        vertical slices)                                  worked; loop)
```

- **1. Requirements** — what are we building, and for whom. → `PROJECT-requirements.md`
- **2. Architecture** — how it's built and where it runs, with the reasoning recorded. →
  `PROJECT-architecture.md` + `PROJECT-adl.md`
- **3. Implementation** — build it, in **vertical slices** (each slice is a thin
  end-to-end piece that itself mini-loops build → test → deploy). → `PROJECT-plan.md`
- **4. Testing** — verify each slice end-to-end, and the system as a whole before a release.
- **5. Deployment** — ship it to the target environment (per slice to dev, per release to
  prod).
- **6. Evaluation** — measure what happened against the success criteria and NFRs: what
  worked, what didn't, what it cost, what to improve. → `PROJECT-evaluation.md`

Evaluation is not the end — it's the hinge. Its findings become new requirements, new ADRs,
bug fixes, or parking-lot items, and the cycle turns again for v1.1, v2, and beyond. **Stages
4–6 are where agentic engineering pulls away from vibe coding**, so the kit makes them
first-class rather than afterthoughts.

### Idea 2 — Each document answers exactly one of the six questions

Good structure comes from never letting two documents own the same fact. The six classic
questions map cleanly onto the doc set:

| Question | Owned by | Answers |
|---|---|---|
| **WHO** | `PROJECT-requirements.md` (§ Users & Personas) | Who uses it, who operates it, single-user vs. multi-tenant |
| **WHAT** | `PROJECT-requirements.md` | What we're building; scope in / deferred / out; FR & NFR |
| **WHERE** | `PROJECT-architecture.md` (§ Deployment target) + ADL | Where it runs — AWS / Azure / GCP / a laptop / a self-hosted server — and the stack, chosen to fit the goal |
| **HOW** | `PROJECT-architecture.md` | How it's built — system design, data model, contracts, sequences |
| **WHY** | `PROJECT-adl.md` | Why each significant choice was made (ADRs) |
| **WHEN** | `PROJECT-plan.md` | When/in what order — slice sequence, status, what's done next |

Plus two supporting docs: `PROJECT-glossary.md` (a running glossary) and
`PROJECT-reference.md` (the raw pre-requirements brain-dump). And `CLAUDE.md` is the compact
session-start context that just *points* at all of the above.

> Rule of thumb: if two docs ever disagree on a design matter, the **architecture doc wins**
> and the other gets fixed — or the contradiction becomes a new ADR.

---

## What's in this folder

```
project-starter/
  KICKOFF.md                       <- you are here: the framework + the prompt to paste
  CLAUDE.md                        <- compact session-start context (template)
  docs/
    PROJECT-requirements.md        <- WHO + WHAT
    PROJECT-architecture.md        <- HOW + WHERE
    PROJECT-adl.md                 <- WHY (Architecture Decision Records)
    PROJECT-plan.md                <- WHEN (sliced roadmap, status board)
    PROJECT-evaluation.md          <- stage 6: measure what shipped; close the loop
    PROJECT-glossary.md            <- running glossary of terms/services
    PROJECT-reference.md           <- raw scoping notes / brain-dump (pre-requirements)
  .claude/skills/
    start-slice/SKILL.md           <- session-start ritual
    wrap-slice/SKILL.md            <- end-of-slice ritual (now includes an evaluation beat)
```

All template files use the token `PROJECT` (and `{{...}}` placeholders) wherever something
project-specific goes. Step 1 below replaces those.

---

## Working principles (carried from CareerVault)

1. **Vertical slices.** Every slice lands deployed and verified end-to-end, not just
   unit-tested. "Works on localhost" isn't an exit criterion unless the slice is
   frontend-only.
2. **ADR before code.** Any decision the architecture doc doesn't already cover gets written
   into the ADL *before* the code that implements it.
3. **Docs current before done.** A slice isn't finished until the next session could
   cold-start from `CLAUDE.md` alone. `/wrap-slice` blocks on the docs.
4. **Cost / resource ceiling.** Pick a hard budget up front (dollars, or "runs on my
   laptop") and put guardrails in. Revisit it before any slice that adds a new paid service.
5. **Learning vehicle.** When live behavior contradicts the docs, surface it and correct the
   doc *with reasoning* — never silently code around it.
6. **Close the loop.** Don't stop at "deployed." Evaluate against the success criteria, and
   feed what you learn into the next turn of the cycle.

---

## How to use this kit (step by step)

**1. Copy the folder into your new repo.**
```bash
cp -R ~/Documents/GitHub/aws-project-starter ~/Documents/GitHub/<your-new-repo>
cd ~/Documents/GitHub/<your-new-repo>
git init
```

**2. Open a fresh Claude Code session in that repo and paste the kickoff prompt below.**
Claude runs a **detailed interview** first — pinning down who / what / where / how / why /
when — *before* writing any doc, then renames the `PROJECT-*` files to your slug and drafts
the requirements.

**3. Work the lifecycle in order.** Requirements before architecture; architecture before
slicing the plan; then build, test, deploy, and evaluate. Each stage's doc is the input to
the next.

**4. Once you're implementing, run the rituals every session:** `/start-slice` to begin,
`/wrap-slice` to finish (it now includes a short evaluation beat).

**5. When a version is done, fill `PROJECT-evaluation.md`** and let its findings seed the
next cycle.

---

## The kickoff prompt (paste this into the new session)

> Copy everything in the block below into your first message in the new repo's session.
> Fill in the one bracketed line with your project idea (a rough sketch is fine — the
> interview exists to flesh it out).

```
I'm starting a new project and I want to build it with agentic-engineering discipline, not
vibe coding. I've brought a reusable framework into this repo from a previous project
(CareerVault): KICKOFF.md, a CLAUDE.md template, docs/PROJECT-*.md skeletons, and two skills
(/start-slice, /wrap-slice).

Read KICKOFF.md FIRST. It explains two things you must follow: (a) the six-stage delivery
lifecycle as a cycle — requirements, architecture, implementation, testing, deployment,
evaluation, then loop; and (b) the doc set, where each document owns exactly one of the six
questions who / what / where / how / why / when.

My project idea: [ONE-TO-THREE SENTENCES ON WHAT YOU WANT TO BUILD. Rough is fine.]

Proceed like this:

STEP 1 — A THOROUGH OPENING INTERVIEW (do this before writing ANY doc).
This interview is the single most important step — it's what makes the difference between a
prototype and something that lasts. Ask focused questions, a few at a time, until you can
answer ALL SIX questions confidently:
  - WHO   — who are the users? Just me (single-user), or multi-tenant later? Who operates/
            runs it? Any distinct personas?
  - WHAT  — what does it do? What's the ONE thing that must be true for it to be worth
            building? What's explicitly in scope, deferred, and out of scope?
  - WHERE — where will this be deployed? AWS, Azure, GCP, a local laptop, a self-hosted
            server, edge, mobile? Do I have a stack preference, or should you recommend the
            best fit for the goal? (Keep the stack OPEN until we decide this together — don't
            assume AWS.)
  - HOW   — any hard technical constraints, must-use or must-avoid technologies, languages,
            or runtimes I already know I want?
  - WHY   — what's the motivation, and what am I trying to learn or achieve? What does
            success look like concretely?
  - WHEN  — any timeline or sequencing priorities? What's the thinnest first slice that would
            prove the whole thing works end-to-end?
Also nail down non-functionals early: a hard cost/resource ceiling, performance and security
expectations. Do NOT write any document until this picture is clear — if something's vague,
ask, don't assume.

STEP 2 — SET UP THE DOCS. Once the picture is clear, pick a short project name + slug, rename
the docs/PROJECT-*.md files and the PROJECT token inside them to that slug, fill the CLAUDE.md
placeholders, and record the deployment target + chosen stack as ADR-001 (the WHERE decision).

STEP 3 — REQUIREMENTS (lifecycle stage 1). Draft PROJECT-requirements.md with me — including
the Users & Personas (WHO) section — and stop for my review before moving on.

STEP 4 — ARCHITECTURE + ADL (stage 2). Only after requirements are approved, design the
architecture (including the WHERE / deployment-target section) and write an ADR for each
significant decision before it's locked in.

STEP 5 — PLAN & BUILD (stages 3–5). Slice the work into PROJECT-plan.md, then build slice by
slice using /start-slice and /wrap-slice. Each slice is tested and deployed end-to-end.

STEP 6 — EVALUATE (stage 6). When a version is done, help me fill PROJECT-evaluation.md —
measure against the success criteria and NFRs, capture what worked and what to improve, and
feed findings back into a new turn of the cycle.

Work one stage at a time. Ask before assuming. Treat the docs as the single source of truth,
following the division of authority and the six-question map in KICKOFF.md.
```

---

## Notes & customization

- **Stack-open by design.** Nothing here assumes AWS (or any cloud). The WHERE decision —
  cloud, local, or self-hosted — is made *with you* during the interview and recorded as an
  ADR. The skeletons stay neutral; you fill in the chosen stack.
- **The rituals reference commands and profiles** (git, a cloud/deploy profile, a test
  command). They use `{{...}}` placeholders you fill once the stack and repo conventions are
  set — usually at the end of the first implementation slice.
- **Keep CLAUDE.md compact.** Its whole job is cheap session-start context that *points at*
  the plan doc's status board. Detail lives in the plan doc, not here.
- **Dial the rigor to the project.** Building a throwaway spike? Run a light interview, skip
  straight to a slice, and formalize later if it earns it. Building something to keep? Run the
  full cycle. The kit supports both ends of the spectrum.
- **This kit is reusable.** After you seed a project from it, leave this folder untouched so
  it's ready for the next one.
```
