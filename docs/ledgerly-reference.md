# Ledgerly — Scoping Notes / Reference

**Status:** Frozen brain-dump — the raw idea before it was structured
**Created:** 2026-07-12

---

> This is the *pre-requirements* document: the unstructured capture of the original idea,
> motivation, and any research done before formal requirements gathering. It's allowed to
> be messy. Once the requirements doc exists, this stops changing — it's a historical
> record of where the idea started, and requirements/architecture/ADL take over.

## The idea (raw)

A budgeting and financial planning app. It should give an at-a-glance view of my finances
so I have a good sense of where my money is going. I should be able to use that
categorization of my finances to help me budget better: I set the categories, then set the
amounts for how much the budget is for each category and how much I want to spend.

The application would be able to see my transaction history. I envision it will be
connected to my bank accounts in some way — the most efficient way to get transaction
history. An AI agent (or as many AI agents as needed) can decipher from the transaction
history what category each transaction should be in and itemize it so I know my budget
based on what I've spent.

Other feature ideas floated during scoping: recurring/subscription detection, savings
goals and month-over-month trends, budget alerts/notifications, and an "ask my finances"
conversational agent. The app should stay open-ended enough to accept new features as
they're conjured up.

## Why build it

- Real personal use: actually understand and control monthly spending.
- Educational project — another vehicle for learning by building. AWS is the platform with
  the most existing access; Python is the language of choice. Specific learning targets
  from the interview: AI agents / LLM pipelines, AWS serverless architecture,
  infrastructure-as-code + CI/CD, and frontend/full-stack skills.

## Rough capabilities imagined

- At-a-glance dashboard of where money goes
- User-defined categories with budget amounts per category
- Transaction history pulled from bank accounts
- AI agent(s) categorize each transaction automatically
- Budget vs. actual per category

## Known unknowns / questions to resolve

- Website vs. mobile app for the UI → resolved in interview: responsive web app first.
- How to connect to banks → resolved for v1: CSV export/import first, live bank
  connection (likely Plaid) as the next ingest source.
- Exact stack — Python preferred, otherwise open → resolved: AWS serverless-first
  (ADR-001).

## Research notes / links

- **Plaid Transactions API** — candidate for bank connectivity and transaction history.
  Free Sandbox with fake bank data; production access is paid per connected account.
  Coverage is strongest in the US (owner's banks are US-based, so viable). To be evaluated
  properly in the architecture stage / the slice that adds live bank sync.
