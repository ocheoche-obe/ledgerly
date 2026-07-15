# Ledgerly

A single-user personal budgeting app: import bank transactions (CSV in v1), let an AI agent
categorize them into owner-defined budget categories, and see budget-vs-actual per category
for each budget cycle at a glance. Built AWS-serverless-first as a deliberate learning
vehicle (AI/LLM pipelines, IaC/CI-CD, full-stack).

> **Start here:** [`CLAUDE.md`](./CLAUDE.md) for project context, and [`docs/`](./docs) for
> the canonical requirements, architecture, decisions (ADL), and implementation plan.

## Layout

```
infra/       CDK app (Python) — one stack per stage, composed of constructs (§5.1)
backend/
  core/      pure domain logic, no AWS imports (portability seam + unit-test surface)
  adapters/  AWS-facing persistence (boto3) — quarantines the SDK away from core/
  functions/ thin Lambda handlers (identity from the verified JWT only)
  tests/     pytest (unit)
frontend/    React + Vite + TypeScript SPA (Cognito Hosted UI, PKCE)
docs/        canonical docs: requirements, architecture, adl, plan, evaluation, glossary
```

## Working on it

Slices are run with the `/start-slice` and `/wrap-slice` rituals (`.claude/skills/`).
Deployment targets the dedicated Ledgerly AWS account (ADR-010) via the `ledgerly-dev`
profile — `us-east-1`, account `816020558700`.

```bash
# Backend tests
cd backend && python -m pytest

# Frontend build
cd frontend && npm ci && npm run build

# Infra (from infra/, with the venv active)
cdk diff  Ledgerly-dev --profile ledgerly-dev      # review before every deploy (ADR-004)
cdk deploy Ledgerly-dev --profile ledgerly-dev
```
