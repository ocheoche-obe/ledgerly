# Ledgerly — Architectural Decisions Log (ADL)

**Status:** Living document — updated as decisions are made
**Last updated:** 2026-11-16

---

## What this is

This file captures the **why** behind significant architectural choices. Each entry is an
**Architecture Decision Record (ADR)** — a lightweight written record of a decision, the
context around it, the alternatives considered, and the consequences accepted.

ADRs are an industry-standard practice because architectural reasoning fades fast: six
months from now, "why did we pick X over Y?" becomes unanswerable unless it's written
down. ADRs preserve that institutional memory.

### Format used here

Each ADR has:
- **Status** — Accepted (decided), Proposed (leaning), Open (TBD), Deferred (revisit later),
  Superseded (replaced by a later ADR — link it).
- **Context** — what situation forced the decision.
- **Decision** — what was chosen.
- **Alternatives considered** — what was rejected and why.
- **Consequences / trade-offs** — what's gained, and what's accepted as cost or risk.

### Cross-reference

- Requirements: `ledgerly-requirements.md`
- Architecture: `ledgerly-architecture.md`
- Glossary: `ledgerly-glossary.md`
- Scoping notes: `ledgerly-reference.md`

### Convention

**ADR before code.** A decision the architecture doc doesn't already cover gets written
here *before* the code that implements it. Number ADRs sequentially and never renumber —
if a decision is reversed, add a new ADR that supersedes the old one and mark the old one
Superseded.

---

## Index

| ID      | Title                                            | Status   |
|---------|--------------------------------------------------|----------|
| ADR-001 | Deployment target: AWS, serverless-first         | Accepted |
| ADR-002 | Backend language / runtime: Python 3.13 on Lambda | Accepted |
| ADR-003 | Frontend stack: React + Vite + TypeScript SPA on S3/CloudFront | Accepted |
| ADR-004 | Infrastructure-as-Code tool: AWS CDK in Python   | Accepted |
| ADR-005 | Database: DynamoDB single-table, on-demand       | Accepted |
| ADR-006 | Tenancy model: single-user, USER#\<sub\> partition scoping | Accepted |
| ADR-007 | Authentication: Amazon Cognito User Pool         | Accepted |
| ADR-008 | AI categorization: Amazon Bedrock + Claude behind a swappable interface | Accepted (amended 2026-08-03: model Opus 4.8 → **Sonnet 4.6**, account cannot invoke Opus 4.8) |
| ADR-009 | Async backbone: SQS queue + DLQ for categorization | Accepted |
| ADR-010 | AWS account topology: dedicated account per project | Accepted |
| ADR-011 | CI/CD deploy federation: GitHub OIDC assuming CDK bootstrap roles | Accepted |
| ADR-012 | Transaction natural key includes the running balance | Accepted |
| ADR-013 | Per-file account identity supplied (and confirmed) at upload time | Accepted |
| ADR-014 | Plaid becomes the primary ingest source (Sandbox only for now) | Accepted |
| ADR-015 | Loan accounts stay out of spend; Plaid Sandbox data lives under its own user | Accepted |
| ADR-016 | Plaid Production on prod, on Plaid's free trial | **Proposed** (awaiting owner) |
| ADR-017 | Transfers between own accounts, from Plaid's own label | **Proposed** (awaiting owner) |

---

## ADR-001: Deployment target — AWS, serverless-first

**Status:** Accepted (2026-07-12, opening interview)

### Context

Ledgerly needs a deployment target (the WHERE). The constraints that drive it:

- **Single user** at personal transaction volume — traffic is near zero most of the time,
  bursty around a monthly import-and-review session.
- **Hard cost ceiling of ~$0–10/month** (NFR-1.1) — an always-on server or database eats
  most of that ceiling doing nothing.
- **Learning is a primary goal**: the owner explicitly wants to learn AWS serverless
  architecture, IaC/CI-CD, and AI/LLM pipelines, and has more existing access to AWS than
  to any other platform.
- **Python** is the owner's preferred backend language and is a first-class serverless
  runtime on AWS.

The starter kit requires this decision be made deliberately, not defaulted.

### Decision

Deploy Ledgerly to **AWS, single-cloud, serverless-first**: prefer managed, pay-per-use
services (e.g. Lambda-class compute, managed API front door, serverless data store,
managed identity) over provisioned servers or containers. Specific service choices are
made per-component in the architecture stage (ADR-002 onward), but each choice starts
from "the serverless option, unless there's a recorded reason not to."

### Alternatives considered

- **AWS with containers/EC2 (always-on)** — simpler mental model, but idle compute cost
  alone approaches the monthly ceiling, and it teaches less of what the owner wants to
  learn. Rejected on cost + learning fit.
- **Another cloud (GCP, Azure)** — comparable serverless offerings, but the owner has the
  most access and familiarity on AWS, and no requirement pulls toward another provider.
  Rejected on access/learning fit.
- **Local / self-hosted first** — zero cost and zero third-party risk, but it defers the
  cloud learning that motivates the project and gives no real deployment stage
  (lifecycle stage 5 would degenerate to "runs on my laptop"). Rejected.
- **PaaS (Fly.io, Render, Vercel-only)** — fastest to ship, but hides exactly the
  infrastructure the owner wants to learn. Rejected on learning fit.

### Consequences

- Near-zero idle cost; the app comfortably fits the ~$10/month ceiling at personal volume.
- The learning goals (serverless, IaC, event-driven design) get first-class exercise.
- **Accepted trade-off: vendor coupling to AWS.** Portability posture is documented in the
  architecture doc §0.1; business logic is kept separable from AWS plumbing but no
  active multi-cloud abstraction is built.
- Accepted trade-off: cold starts and distributed-system debugging complexity — fine for a
  single user, and itself a learning surface.
- Every later component ADR (002–008) inherits this posture as its starting context.

---

## ADR-002: Backend language / runtime — Python 3.13 on AWS Lambda

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

ADR-001 fixed AWS serverless-first. The interview recorded a strong owner preference for
Python (also an interview constraint for skill-building). The backend surface is small:
CRUD APIs, a CSV parser, and an LLM categorization pipeline.

### Decision

All backend compute is **Python 3.13 on AWS Lambda**. Business logic (cycle math, CSV
normalization, categorization prompting) lives in plain Python modules with thin Lambda
handlers on top, keeping logic separable from AWS plumbing (ADR-001 portability posture).

### Alternatives considered

- **TypeScript on Lambda** — one language across the stack, but contradicts the stated
  Python preference/constraint. Rejected.
- **Python in containers (Fargate/App Runner)** — simpler local dev, but always-on cost
  pressure against NFR-1.1 and weaker serverless learning fit. Rejected.

### Consequences

- First-class Lambda runtime; best ecosystem for the AI pipeline (boto3, Bedrock).
- Cold starts are acceptable at single-user volume; keep functions small and avoid heavy
  dependencies in hot paths.
- Frontend remains TypeScript (ADR-003) — two languages, each in its natural home.

---

## ADR-003: Frontend stack — React + Vite + TypeScript SPA on S3/CloudFront

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

FR-5 requires a responsive web dashboard; NFR-7.1 an at-a-glance single screen; the owner
wants transferable frontend skills. The app is fully authenticated (no SEO/SSR need).

### Decision

A **static React + Vite + TypeScript single-page app**, served from **S3 behind
CloudFront**. The SPA authenticates against Cognito (ADR-007) and calls the API with a
JWT. Deployed as plain files from the same CDK app (ADR-004).

### Alternatives considered

- **Next.js on Amplify Hosting** — SSR the app doesn't need, and Amplify manages infra
  outside the CDK app, splitting deployment into two systems. Rejected.
- **Vue/Svelte SPA** — same hosting shape, smaller ecosystems, less transferable.
  Rejected on learning fit.

### Consequences

- Hosting cost ≈ pennies; TLS and caching via CloudFront.
- React + TypeScript is the highest-transfer frontend skill.
- SPA-only means auth tokens are handled client-side — use the standard Cognito SPA flow
  (Authorization Code + PKCE) rather than anything hand-rolled.

---

## ADR-004: Infrastructure-as-Code tool — AWS CDK in Python

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

NFR-5.1 requires all infra as code; IaC/CI-CD is a primary learning goal. Candidates:
CDK, SAM, Terraform.

### Decision

**AWS CDK in Python** defines all infrastructure. One CDK app, constructs per component
(auth, data, API, ingest, categorization, web), synthesizing to CloudFormation.

### Alternatives considered

- **AWS SAM** — simplest for pure serverless with `sam local`, but declarative YAML is
  less expressive and the skill transfers less broadly. Rejected.
- **Terraform** — most transferable multi-cloud IaC skill, but adds a second language
  (HCL) and self-managed state; the learning budget is better spent going deep on AWS.
  Rejected for v1 (a future project can pick it deliberately).

### Consequences

- Infra and app share one language and toolchain; infra is real code (types, loops,
  reuse).
- CDK compiles to CloudFormation, so CFN concepts get learned underneath.
- Accepted cost: CDK's abstractions can hide resource details — mitigate by reviewing
  synthesized templates (`cdk diff`) as a learning habit.

---

## ADR-005: Database — DynamoDB single-table, on-demand capacity

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

The data is small (hundreds of transactions/month), access patterns are well-known and
few, budgets are keyed per budget cycle (FR-4.2/4.3), ingest must be idempotent
(FR-2.2), and NFR-1.1's $10 ceiling punishes always-on databases. NFR-3.1 requires
durable, non-lossy storage.

### Decision

A single **DynamoDB table** (on-demand billing) holds all entities, designed
**access-pattern-first** (architecture doc §2): user-scoped partition keys (ADR-006),
date-sorted transaction sort keys for cycle-window queries, a GSI for category
drill-down, and a sparse GSI for the review queue. Idempotency via deterministic
transaction IDs + conditional writes. Point-in-time recovery on.

### Alternatives considered

- **Aurora Serverless v2 (Postgres)** — full SQL, but minimum-capacity pricing genuinely
  threatens the $10 ceiling and adds VPC networking to every Lambda. Rejected on NFR-1.1.
- **S3 + Athena / flat files** — near-zero cost but no low-latency interactive reads
  (NFR-2.1/2.3). Rejected.

### Consequences

- ≈ $0/month at Ledgerly volume; no connections, no VPC, serverless-native.
- Queries must be designed up front; ad-hoc questions later may need a new GSI or an
  export. Accepted — and the access-pattern-first discipline is itself a learning goal.
- Cycle-aware keys make “budget vs. actual per cycle” a pair of Query calls, not a scan.

---

## ADR-006: Tenancy model — single-user, USER#\<sub\> partition scoping

**Status:** Accepted (2026-07-13, architecture stage; owner-approved — makes the interview direction concrete)

### Context

v1 has exactly one user, but FR-1.3 requires every record scoped to the authenticated
identity from the token, and §2 requires the data model be multi-tenant-ready.

### Decision

Every DynamoDB item's partition key is prefixed **`USER#<sub>`**, where `<sub>` is the
Cognito subject claim of the authenticated caller — taken **only** from the verified JWT,
never from the request body. All queries are partition-scoped by construction.

### Alternatives considered

- **No user scoping** — simpler keys, but violates FR-1.3 and turns future multi-tenancy
  into a re-keying migration. Rejected.
- **Full multi-tenancy now** (self-signup, isolation testing) — out of scope for v1 (§3).
  Rejected.

### Consequences

- Adding users later is an auth/product change (enable signup), not a data migration.
- Cross-user data leakage is structurally impossible while handlers derive the partition
  from the token.
- Single-user volume in one logical partition is far below DynamoDB partition limits.

---

## ADR-007: Authentication — Amazon Cognito User Pool

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

FR-1 requires real login with no anonymous surface and exactly one owner-provisioned
account; NFR-4.1 requires a managed IdP. The API and SPA need a standard token flow.

### Decision

An **Amazon Cognito User Pool** with self-signup disabled and a single admin-created
user. The SPA uses the Authorization Code + PKCE flow; **API Gateway's JWT authorizer**
validates tokens before any Lambda runs (FR-1.1). The token's `sub` claim is the user
identity for all data scoping (ADR-006).

### Alternatives considered

- **Auth0 / Clerk** — better DX, but adds a third-party vendor to a bank-data app,
  config outside IaC, and shifting free tiers. Rejected.
- **CloudFront basic auth / shared secret** — fails NFR-4.1 and forecloses identity
  scoping. Rejected.

### Consequences

- Free at this scale; defined in the same CDK stack; native API Gateway integration means
  unauthenticated requests never reach application code.
- Accepted cost: Cognito's DX is clunky — treated as an AWS learning surface.
- Future multi-user = enable signup + (maybe) groups; no architectural change.

---

## ADR-008: AI categorization — Amazon Bedrock + Claude, behind a swappable interface

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

FR-3 requires automatic categorization with confidence, a review queue, and corrections
that improve accuracy; success criterion 2 sets an ≥80% accuracy bar; NFR-6.1 requires
the model/provider be swappable; NFR-4.3 forbids secrets in code; NFR-1.2 requires the
billing alarm to guard total spend. Expected volume ≈ 500 transactions/month → roughly
10–15 LLM calls/month (batched), well under $1/month on any current Claude model.

### Decision

Categorization calls **Claude Opus 4.8 via Amazon Bedrock** (model ID
`anthropic.claude-opus-4-8`), using the Anthropic SDK's Bedrock client. The pipeline
(architecture doc §3.2):

1. **Merchant rules first** — owner corrections persist as `merchant → category` rules;
   an exact-match hit skips the LLM entirely (fast, free, and the FR-3.4 learning loop).
2. **LLM for the rest** — batched transactions + the owner's category list + recent
   corrections as few-shot examples; **structured output** (strict tool/JSON schema) so
   every result is `{category, confidence}`; low confidence flags the review queue.
3. All calls go through a thin `Categorizer` interface so the model or provider is a
   config change plus a superseding ADR, not a rewrite.

### Alternatives considered

- **Direct Anthropic API** — full feature surface, but requires an API key in Secrets
  Manager and puts LLM spend on a second bill outside the AWS billing alarm. Rejected.
- **Claude Platform on AWS** — IAM auth + same-day parity; strong option, but newer and
  Bedrock is the established AWS-native learning path. Not chosen for v1.
- **Smaller/cheaper models (Sonnet 5, Haiku 4.5)** — all fit the ceiling; Opus 4.8 chosen
  because categorization accuracy *is* the product (criterion 2) and the cost delta is
  cents. The eval harness (NFR-5.3) makes a later downgrade a measured decision.
- **No LLM (rules/embeddings only)** — cheaper but guts the primary learning goal and
  handles novel merchants poorly. Rejected.

### Consequences

- **Zero runtime secrets**: Bedrock is called with the Lambda's IAM role; least-privilege
  policy scoped to the one model (NFR-4.3/4.4). LLM spend lands on the AWS bill, so the
  NFR-1.2 billing alarm covers it automatically.
- Estimated LLM cost ≈ $0.50–1/month at expected volume ($5/$25 per MTok).
- Accepted: Bedrock can lag the first-party API on new features (e.g. Batches API) —
  irrelevant at this volume; revisit if the deferred chat feature needs more surface.
- Model choice is revisit-cheap: the eval harness measures accuracy per model, and a swap
  is config + ADR.

### Implementation notes (Slice 5, 2026-07-21)

- **Called through boto3, not the `anthropic` SDK.** The categorizer invokes Bedrock via
  `boto3` `bedrock-runtime.invoke_model` with the native Anthropic Messages body
  (`anthropic_version: bedrock-2023-05-31`), *not* the `anthropic[bedrock]` package. boto3 is
  already ambient in the Lambda runtime and the adapters' SDK, so this preserves the
  zero-runtime-deps posture (no pip/layer step) the Lambda asset relies on — the same reasoning
  as the hand-rolled ULID. Structured output is a **forced tool call** (`record_categorizations`)
  with thinking disabled — the most portable machine-readable-output path across Anthropic
  models on Bedrock, and the setting Bedrock requires alongside a forced `tool_choice`.
- **Opus 4.8 is INFERENCE_PROFILE-only on Bedrock** (verified live via
  `bedrock list-foundation-models`): direct on-demand `invoke_model` on the bare
  `anthropic.claude-opus-4-8` foundation-model id is not supported. The deployed
  `BEDROCK_MODEL_ID` is therefore the **inference-profile** id `us.anthropic.claude-opus-4-8`
  (ACTIVE in the account), and the least-privilege IAM grant covers **both** the profile ARN
  *and* the underlying foundation-model ARN across regions (a cross-region profile fans out).
  Same shape for the eval's Sonnet 5 A/B (`us.anthropic.claude-sonnet-5`).

### Amendment (2026-08-03): model changed to Sonnet 4.6 — Opus 4.8 is not invocable here

**Status: Accepted, amended.** The decision (Bedrock + Claude behind a swappable interface)
stands unchanged. The *model* does not: **this AWS account cannot invoke Opus 4.8**, so the
categorizer now runs **Claude Sonnet 4.6** (`us.anthropic.claude-sonnet-4-6`).

**What happened.** Slice 5 was deployed 2026-07-21 and every categorizer invocation failed with
`AccessDeniedException: anthropic.claude-opus-4-8 is not available for this account`. Nobody
noticed for 12 days because the slice's live exit criteria were never run (see the Slice 5
completion notes; the process lesson is now a binding convention in `CLAUDE.md`).

**It was not a missing model agreement.** That was the first hypothesis and it was wrong. The
owner accepted the Bedrock model agreement for Opus 4.8 on 2026-08-03 — CloudTrail confirms
`CreateFoundationModelAgreement` succeeded, and `agreementAvailability` flipped
`NOT_AVAILABLE → AVAILABLE`. **Invocation was still denied**, 40+ minutes later, in all three
regions the `us.` profile fans out to, via both `InvokeModel` and `Converse`. Accepting the
Sonnet 5 agreement as a control produced the same result. All four availability fields
(`agreementAvailability`, `entitlementAvailability`, `authorizationStatus`,
`regionAvailability`) read `AVAILABLE`/`AUTHORIZED` for a model that cannot be called.

**The measured boundary** on account `816020558700`, us-east-1:

| Invocable | Denied (`AccessDeniedException`) |
|---|---|
| Haiku 4.5 · Sonnet 4.5 · **Sonnet 4.6** | Opus 4.7 · **Opus 4.8** · Sonnet 5 |

The cut is by model tier, not vendor: Claude 3 Haiku returns a *different* error (legacy-model
policy), so the account reaches model-specific checks rather than being blocked from Anthropic
wholesale. This is **account-tier eligibility**, and the error text says so — *"contact AWS
Sales for additional access options"*. The owner is raising a request for frontier-tier access
separately; it is not a blocker for Ledgerly.

**Why Sonnet 4.6.** It is the strongest model the account can actually invoke. Cost did not
drive the choice and should not have: at Ledgerly's volume the whole 153-transaction backlog is
roughly **$0.09** on Sonnet 4.6 versus **$0.03** on Haiku 4.5, and steady state is ~$0.12/month
versus ~$0.04/month. Both are rounding errors against the $10/month ceiling (NFR-1.1), so the
sensible move is to buy quality with pennies rather than optimise the pennies.

**Interim, explicitly.** Revisit → Sonnet 5 when the eligibility request lands. That is a
two-line change in `infra/ledgerly/config.py` plus a redeploy.

**What this vindicates.** The original ADR claimed "model choice is revisit-cheap: a swap is
config + ADR." That claim is now *tested* rather than asserted — the swap touched
`BEDROCK_MODEL_ID` / `BEDROCK_FOUNDATION_MODEL` in one config module (which feeds both the
runtime env var and the IAM grant), plus docstrings and test fixtures. No logic changed. The
`Categorizer` interface and the pure `core/categorize/` decision matrix were untouched.

**Knock-on:** the eval harness A/B pair changes from *Opus 4.8 vs Sonnet 5* (neither invocable,
so the comparison was unrunnable) to **Sonnet 4.6 vs Haiku 4.5** — which is a better question
anyway: *is the ~3× cheaper model good enough for a 15-category classification?* Both can
actually be called. The eval itself remains deferred by owner decision ([B-8]).

---

## ADR-009: Async backbone — SQS queue + DLQ for the categorization pipeline

**Status:** Accepted (2026-07-13, architecture stage; owner-approved)

### Context

FR-3.5: categorization runs asynchronously and must never block or fail an import; a
failed categorization lands in Uncategorized, never lost (NFR-3.1). NFR-6.1 wants future
features to subscribe to events rather than rewiring.

### Decision

Import and categorization are decoupled by an **SQS queue**: the import Lambda persists
transactions, records the import summary, and enqueues categorization jobs; a categorizer
Lambda consumes batches. Failed messages retry, then land in a **dead-letter queue** with
an alarm; DLQ'd transactions remain `Uncategorized` (they were persisted at import time,
so nothing is lost).

### Alternatives considered

- **EventBridge bus** — the most extensible shape, but a second subscriber doesn't exist
  yet, and the categorizer would still want SQS behind the rule for batching/DLQ. Deferred:
  introduce EventBridge when the first additional subscriber (alerts/trends) arrives —
  that is the recorded trigger.
- **DynamoDB Streams** — zero extra infra but couples the pipeline to low-level record
  events and makes per-import batching awkward. Rejected.
- **Synchronous** — violates FR-3.5 and risks API timeout on large imports. Rejected.

### Consequences

- Import returns fast regardless of LLM latency; retries and failure isolation are
  built-in; ≈ $0 at this volume.
- The queue is the seam where EventBridge slots in later without touching the categorizer.

---

## ADR-010: AWS account topology — a dedicated account for Ledgerly

**Status:** Accepted (2026-07-13, Slice 1 setup)

### Context

The owner already runs a separate project (CareerVault) in AWS account `768396678224`,
accessed via AWS IAM Identity Center (SSO) with an `AdministratorAccess` permission set.
Ledgerly needs its own AWS footprint. The architecture doc (§0.1) already specifies
Ledgerly uses **one AWS account with two CDK stages** (`dev`/`prod`) — but is silent on
whether that account is *shared with CareerVault* or *dedicated to Ledgerly*. Two forces
make this worth deciding deliberately:

- **Blast-radius / isolation.** The owner's explicit concern: never accidentally alter the
  wrong project's resources. A profile only enforces isolation if it authenticates into a
  *different account*; two profiles over one account are just labels with no AWS-enforced
  boundary.
- **Cost attribution.** NFR-1.1 sets a **$10/month ceiling for Ledgerly specifically**. A
  shared account commingles two projects' spend on one bill, blurring the ceiling and its
  billing alarm; a dedicated account makes the whole account bill == Ledgerly's spend.

### Decision

Provision a **dedicated AWS account for Ledgerly** as a member account under the owner's
existing AWS Organization, reachable through the *same* IAM Identity Center. Ledgerly's
`dev` and `prod` stages remain CDK stages **within that one dedicated account** (unchanged
from §0.1). Local access is a distinct `ledgerly-dev` profile whose `sso_account_id` is the
new account — never `768396678224`.

### Alternatives considered

- **Share the CareerVault account (`768396678224`), isolate by resource naming** — no new
  account to create; fastest start. Rejected: isolation is convention-only (a mistyped
  command can hit CareerVault), and the two projects' costs commingle, defeating the
  per-project ceiling and its alarm.
- **A second, separate AWS Organization / standalone account** — maximal isolation, but
  redundant: one Organization + Identity Center already exists and cleanly supports
  multiple member accounts under one login. Rejected as unnecessary overhead.

### Consequences

- **AWS-enforced isolation:** the `ledgerly-dev` profile physically cannot see or mutate
  CareerVault resources — it authenticates into a different account. Directly satisfies the
  owner's "wrong project" concern.
- **Clean cost attribution:** the dedicated account's bill *is* Ledgerly's spend; the
  Slice-1 billing alarm ($5 actual / $8 forecast, NFR-1.2) measures Ledgerly alone.
- **One login, many accounts:** the same Identity Center login serves both profiles;
  `ledgerly-dev` reuses the existing SSO session, only the target account differs.
- **Setup cost:** a one-time account-creation + permission-set assignment in the
  Organization management account, plus a `cdk bootstrap` of the new account (Slice 1).
- **Mandatory safety gate:** before any `cdk` command, verify
  `aws sts get-caller-identity --profile ledgerly-dev` returns the *new* account id, not
  `768396678224`.

---

## ADR-011: CI/CD deploy federation — GitHub OIDC assuming CDK bootstrap roles

**Status:** Accepted (2026-07-15, Slice 2)

### Context

Slice 1 deployed by manual `cdk deploy` from the workstation — explicitly acceptable only
for the first slice (architecture §5.4). Slice 2 automates it: GitHub Actions must deploy
`dev` on push to `main` and `prod` on manual approval, **with no long-lived AWS keys stored
in GitHub** (NFR-4.3 in spirit). The architecture doc (§5.4) already fixes the shape —
GitHub Actions → OIDC federation into a deploy role → tests → `cdk diff` → deploy — but is
silent on *how much permission that federated identity holds*. This is a security decision
(the identity is reachable by any workflow run on the repo) and belongs in an ADR before the
IAM is written.

`cdk bootstrap` (run in Slice 1) already provisioned a set of scoped roles in the account:
a `*-deploy-role` (drives the deployment) and a `*-cfn-exec-role` (the role CloudFormation
actually uses to create/modify resources, holding the broad service rights). The question is
whether the GitHub-facing OIDC role *reuses* these or holds broad rights itself.

### Decision

The GitHub OIDC identity provider trusts this repo only; the **OIDC role is narrow** — its
only permissions are `sts:AssumeRole`/`sts:TagSession` on the CDK bootstrap roles
(`cdk-hnb659fds-*-816020558700-us-east-1`). Deploys run `cdk deploy` against those roles, so
the broad CloudFormation/service permissions live in the **CFN execution role**, never in
the federated identity. The OIDC trust policy scopes `sub` to exactly two subjects — the dev
auto-deploy (`repo:ocheoche-obe/ledgerly:ref:refs/heads/main`) and the prod job
(`repo:ocheoche-obe/ledgerly:environment:prod`) — so a PR branch or a fork cannot assume the
role. The `prod` deploy is additionally gated behind a GitHub Environment with a required
reviewer (the owner) rather than by a distinct AWS identity.

### Alternatives considered

- **Broad custom deploy role assumed directly by GitHub** — one policy carrying
  `cloudformation:*` + every service CDK touches (S3, DynamoDB, Lambda, Cognito, CloudFront,
  IAM `CreateRole`/`PassRole`, …). Simpler to read in one place, but the federated identity
  reachable from CI holds account-wide power, and it duplicates permissions the bootstrap
  roles already encapsulate. Rejected: larger blast radius for the internet-reachable
  identity, and non-idiomatic for CDK.
- **Long-lived IAM access keys in GitHub secrets** — rejected outright: stored static
  credentials violate NFR-4.3's spirit and the architecture's "zero runtime secrets" stance;
  OIDC is the whole point.

### Consequences

- **Least-privilege entry point:** the only thing GitHub's identity can do is assume the
  pre-scoped CDK roles; broad rights stay in the CloudFormation execution role that only
  CloudFormation uses.
- **Idiomatic + low-maintenance:** as new constructs need new permissions, the bootstrap
  roles carry them — the OIDC role's policy never changes.
- **Coupled to bootstrap:** re-bootstrapping or changing the CDK qualifier means updating the
  OIDC role's `AssumeRole` resource ARNs. Acceptable and rare.
- **Approval is a GitHub gate, not an AWS one:** `prod` protection depends on the GitHub
  Environment reviewer rule; both stages ultimately assume roles in the same account
  (consistent with §0.1's one-account/two-stage model).

---

## ADR-012: Transaction natural key includes the running balance

**Status:** Accepted (2026-07-19, Slice 4)

### Context

Slice 4 ingests bank-export CSVs and must be idempotent (FR-2.2): re-uploading the same
file, or overlapping exports of the same account, must not create duplicate transactions.
The architecture (§2.4) fixes dedupe as *key-equality* on a content-derived natural key —
`txnId = sha256(accountId · date · amountCents · rawDescription)[:16]` — because bank CSVs
carry **no stable per-transaction identifier**. Two exports of the same posted transaction
therefore produce the same `txnId` and the conditional put makes the second a no-op. Clean —
until the owner's real Chase checking export was examined.

Real exports contain **legitimately distinct transactions that are identical** across
`date`, `amountCents`, and `rawDescription`:

- three `TST* MIRRA VR BELLEVUE` charges of `-$31.76`, all posted `06/29/2026`;
- numerous `-$3.00` `MTA*NYCT PAYGO` subway rides posted on the same day.

Under the §2.4 key these collapse to one `txnId`, so an import would **silently drop** the
2nd and 3rd MIRRA charge and every duplicate subway ride — under-counting real spend on
exactly the small, repeated purchases a budgeting app must get right. This is a correctness
bug, not an edge case, and it is invisible (the import summary would report the dropped rows
as "duplicates").

The export does carry one field that distinguishes these rows: the running **`Balance`**
after each posting. Balance is a historical fact — the balance after a given posted
transaction never changes — so it is **stable across re-exports and overlapping exports**,
the property FR-2.2 depends on, while differing between same-day identical charges (the three
MIRRA rows show 3285.11 / 3316.87 / 3348.63).

### Decision

Extend the transaction natural key to include the post-transaction running balance:

```
txnId = sha256(accountId · date · amountCents · rawDescription · balanceCents)[:16]
```

`balanceCents` is the `Balance` column parsed to integer cents (the same treatment as
`amountCents`). Everything else in the architecture's dedupe design is unchanged: the key is
still content-derived, dedupe is still `PutItem` + `attribute_not_exists(sk)` key-equality,
and file-level idempotency via `FILEHASH#<sha256>` (AP 12) still short-circuits whole-file
re-uploads before rows are even considered. Architecture §2.4 is updated to this formula in
the same slice (doc bumped, no other design change).

### Alternatives considered

- **Keep the §2.4 key as written** — matches the doc, no ADR. Rejected: silently drops
  legitimate same-day/same-amount/same-merchant transactions, under-counting spend with no
  signal to the owner. A budgeting app cannot quietly lose transactions.
- **Within-file occurrence index** — append an ordinal (`:0`, `:1`, `:2`) to disambiguate
  identical rows within a file. Rejected: not stable across overlapping exports — if one
  export starts mid-day and includes only two of the three MIRRA charges, the ordinals shift
  and dedupe against the full export breaks, reintroducing duplicates (violates FR-2.2).
- **Require a bank-provided transaction ID** — not available in Chase CSV exports (and the
  point of FR-2.3's source abstraction is to tolerate thin sources). Deferred to if/when a
  richer source (e.g. Plaid, which does provide stable IDs) is added — that source's parser
  can key on the real ID and this content-hash path stays the CSV fallback.

### Consequences

- **No silent transaction loss:** genuinely distinct same-day identical charges are all
  retained; only true re-imports of the *same* posted transaction dedupe.
- **FR-2.2 preserved:** balance is stable per posted transaction, so re-uploads and
  overlapping exports still collapse to no-ops.
- **Assumes `Balance` is present and stable.** True for Chase checking exports (the only
  source this slice). A future source lacking a running balance would need its own key
  strategy in its parser — acceptable, since FR-2.3 already makes the parser pluggable per
  format and the natural-key construction lives behind that seam.
- **Pending/authorized-but-unposted rows** are out of scope: Chase's downloadable CSV
  contains only posted transactions, which is where a stable balance exists. If a future
  source emits pending rows, its parser owns that decision.

---

## ADR-013: Per-file account identity supplied (and confirmed) at upload time

**Status:** Accepted (2026-07-19, Slice 4)

### Context

`accountId` is part of the transaction natural key (ADR-012, architecture §2.4) and FR-2.1
requires the account be "identifiable per file at upload time." A bank CSV's *rows* do not
name the account; the identity lives outside the row data — in the owner's knowledge of which
account they exported. Chase encodes it in the **filename** (`Chase5980_Activity_...csv`,
where `5980` is the account's last four). The question is how Ledgerly obtains `accountId`:
infer it, or have the owner state it.

Because `accountId` feeds the dedupe key, it must be **consistent across every export of the
same account** — if the same account is labelled `chase-5980` in one import and `chase` in
another, dedupe silently fails and duplicates accumulate. So whatever supplies it must be
stable and owner-visible, not a guess buried in the parser.

### Decision

The account identity is a **first-class upload parameter, confirmed by the owner**:

- `POST /imports` accepts an `accountLabel` alongside the filename; it is stored on the
  `IMPORT#` item and copied onto every `TXN#` the file produces.
- The upload UI **pre-fills** `accountLabel` by parsing the filename (`Chase5980...` →
  `Chase ...5980`), and the owner can confirm or edit it before uploading.
- `accountId` (the natural-key component) is the normalized form of that label
  (lower-kebab, e.g. `chase-5980`), computed in `core/` so it is deterministic and unit-tested.

Identity is thus owner-asserted at upload, with filename parsing as a convenience default —
never a silent inference the owner can't see or correct.

### Alternatives considered

- **Silently derive `accountId` from the filename, no UI field** — least code now. Rejected:
  fragile (a renamed download, a browser "(1)" suffix, or a different bank's filename scheme
  breaks it) and invisible — a wrong or shifted inference corrupts the dedupe key with no
  chance for the owner to catch it. Filename parsing is kept, but only as an editable default.
- **Infer the account from row contents** — impossible; Chase rows don't name the account.
- **A managed "accounts" entity the owner creates first, then selects at upload** — the
  clean long-term model for multiple accounts, but heavier than a single-user MVP with one
  checking account needs. Deferred: `accountLabel` is free text now; promoting it to a
  first-class Account entity (with a picker) is a natural later slice if account count grows.

### Consequences

- **Stable, visible key component:** the owner sees and confirms the account each import, so
  the dedupe-critical `accountId` stays consistent across exports of the same account.
- **Multi-account-ready without new infra:** different labels naturally partition
  transactions by account today; a future Account entity can back-fill from the labels.
- **Owner responsibility:** if the owner types two different labels for one account, dedupe
  keys diverge. Mitigated by the filename-derived default (the same file pattern yields the
  same suggestion) and, later, by a first-class account picker.
- **Trusted identity boundary unchanged:** `accountLabel` describes *which bank account* a
  file is; it is never the *user* identity, which still comes solely from the JWT (FR-1.3).

---

## ADR-014: Plaid becomes the primary ingest source (Sandbox only for now)

**Status:** Accepted (2026-11-15, Slice 9 — owner sign-off, including pending transactions counting toward spend; proposed 2026-11-14)

### Context

Ingest has been CSV upload since Slice 4. The owner is pivoting the primary source to Plaid
ahead of the trigger recorded in architecture §1.3 ("v1 success criterion 1 met + owner
appetite to revise the cost ceiling") — an explicit owner decision to reorder the roadmap,
recorded here rather than made silently.

The architecture already anticipated this: §1.2 treats Plaid as "just another producer that
writes transactions and enqueues categorization jobs". The categorizer, cycle engine, budgets
and dashboard are therefore unchanged. What Plaid does force is everything the CSV path never
needed:

- **Ledgerly's first runtime secrets.** Plaid API keys and a per-connection access token.
  Architecture §4.3 is "there are no runtime secrets", with a standing rule that Plaid tokens go
  in Secrets Manager (NFR-4.3/4.5).
- **Ledgerly's first outbound call to a non-AWS service**, from Lambdas whose asset has no
  `pip` step (zero runtime dependencies).
- **Mutable transactions.** A CSV row never changes. Plaid's `/transactions/sync` returns
  `added`, `modified` and `removed`, and a pending charge that posts arrives as a *remove* plus an
  *add* under a **new** `transaction_id`.
- **A different identity.** Plaid supplies a stable `transaction_id` and no running balance, so
  ADR-012's content-hash natural key neither applies nor is needed (ADR-012 said as much).
- **A storage key that embeds the date** (`TXN#<date>#<txnId>`), while `removed` carries only
  the `transaction_id` and `modified` may change the date.

Plaid Dashboard state read on 2026-11-14 (read-only): environments authorized = Sandbox and
Production; Transactions is enabled in both; **no trial products are listed**; no redirect URIs
and no webhook receivers are registered; one Link customization (`default`).

### Decision

**Scope: Plaid Sandbox only, `dev` stage only.** The `prod` stack gets no Plaid routes, no Plaid
secrets and no UI. Going to Plaid Production is a separate ADR.

1. **Where Plaid fits**
   - `POST /plaid/link-token` and `POST /plaid/exchange` (new `api_plaid` Lambda, behind the
     existing JWT authorizer). The exchange stores the access token, writes a `PLAIDITEM#<itemId>`
     item (institution, accounts, cursor — never the token), and triggers the first sync.
   - `POST /plaid/sync` starts a sync and returns an import ID; the work runs in a separate
     **`plaid_sync` worker Lambda** (async-invoked). It loops `/transactions/sync` to the end,
     maps each transaction through a new pure `core/plaid_normalize.py` into
     `core/transactions.to_item`, writes, then saves the cursor, then enqueues categorization for
     newly added rows — the same order and best-effort enqueue as the CSV importer.
   - **A sync is recorded as an `IMPORT#` item** (source `plaid`; counts added / modified /
     removed / skipped), so the existing import report and polling serve it.
   - **Secrets Manager holds both secrets** (the §4.3 standing rule, followed as written): one
     secret for the Plaid API keys, whose value the owner sets by hand; one for access tokens,
     written by the exchange Lambda. Each Lambda gets IAM on only the secret it needs. Values are
     never logged, never returned to the browser, never in CDK or the repo.
   - **Plaid calls use stdlib `urllib`** behind `adapters/plaid.py` — five endpoints, no SDK, no
     change to the Lambda build. Request/response shapes are checked against Plaid's published
     API reference at implementation time, not written from memory.
   - Link is initialized with `transactions` as the only required product, and `identity`
     consented-but-unused, so account-ownership verification can be added later without sending
     the owner back through Link. Cached account balances arrive with the account list at no
     charge and are stored on the `PLAIDITEM#` item at each sync.
2. **Dedupe and mutation**
   - `txnId` **is Plaid's `transaction_id`, verbatim.** Dedupe stays key-equality on the existing
     conditional put (AP 7). It cannot collide with the 16-hex CSV IDs.
   - A **pointer item `PLAIDTXN#<transaction_id>` → date** is written with each transaction, so
     `modified` and `removed` can find a row whose sort key embeds a date they do not carry.
   - **Pending transactions are stored and shown** (owner decision, 2026-11-15), flagged
     `pending: true`. They count toward a category's spend, and the cycle summary reports how much
     of each figure is still pending so the dashboard can say so. A pending amount is provisional:
     it can change when the charge posts (tips, fuel and hotel holds) or disappear if a hold
     drops off.
   - **A pending charge that posts is one transaction, not two.** Plaid reports it as a `removed`
     pending ID plus an `added` posted row carrying `pending_transaction_id`. Within a sync, all
     pages are buffered and the posted rows are applied *before* the removals: the posted row
     inherits the pending row's category, status, confidence and review flag, the pending row is
     deleted, and nothing is re-categorized. If the removal and the posted row arrive in
     *different* syncs, the link is gone — the posted row is categorized afresh, and an owner
     correction made on the pending row is lost unless a merchant rule (Slice 7) re-applies it.
   - `added` → conditional put, enqueue if new. `modified` → update source fields in place,
     **preserving category, status and confidence**; if the date changed, delete-and-put in one
     transaction carrying those fields across. `removed` → delete the row and its pointer, counted
     in the import report. Plaid's sign convention is inverted on the way in (Plaid positive =
     money out; Ledgerly negative = debit). `balanceCents` becomes optional.
3. **Trigger: a "Sync now" button, plus one automatic sync right after linking.** No schedule, no
   webhooks in this slice.
4. **CSV import stays, unchanged**, as the second source behind the same seam (FR-2.3).

**Cost ceiling: NFR-1.1 stays at $10/month and is not revised by this ADR.** Plaid Sandbox is
free. The AWS increment is two Secrets Manager secrets in `dev` ≈ **$0.80/month**, taking the
expected steady state from ≈ $2–4 to ≈ $3–5. The owner states Plaid's Trial plan is also free;
that is not confirmed by the Dashboard, which lists no trial products on this account, and it is
out of scope here. **No Production Item may be created until a follow-up ADR records verified
Plaid pricing against the ceiling** (NFR-1.1's own rule).

### Alternatives considered

- **Access token in SSM Parameter Store (SecureString)** — free, same IAM posture, and arguably
  satisfies NFR-4.3's "a secrets manager". Rejected for now because §4.3 names Secrets Manager
  and $0.80/month fits; it is the fallback if the ceiling tightens.
- **Access token in DynamoDB** — rejected: it would sit beside the data it unlocks, in every
  PITR backup, readable by every Lambda with table access.
- **`plaid-python` SDK** — rejected: needs a dependency-bundling step the Lambda asset does not
  have, for five HTTP calls.
- **Sync inline in the API Lambda** — simpler, but capped by API Gateway's 30-second integration
  limit (Plaid notes the first sync after a history backfill can be several times slower), and it
  is not the shape a webhook would invoke later. The worker is.
- **Hashing `transaction_id` to 16 hex** — keeps IDs uniform, loses traceability to Plaid for no
  gain.
- **Skipping pending transactions** (the original proposal) — simpler, and the same view the CSV
  exports gave, but the dashboard would lag the bank by the 1–3 days a charge takes to post. The
  owner wants pending spend visible, so the reconciliation above is accepted as the price.
- **Showing pending but leaving it out of "spent"** — keeps every figure final, but understates
  what has actually left the budget, which is the question the dashboard exists to answer.
- **Tombstoning removed transactions** instead of deleting — every read path would have to filter
  them. PITR is the recovery story.
- **A lookup GSI on the Plaid ID** instead of pointer items — a third index for one access
  pattern.
- **Scheduled polling** — Plaid's guidance is explicit that freshness is Plaid-driven and a
  polling schedule is not the intended mechanism.
- **Webhooks now** — the right long-term trigger, deferred because it needs three things that
  each deserve their own decision: a public unauthenticated route (FR-1.1 says there is none), an
  ES256 JWT verification library (Plaid says not to hand-roll it; that ends zero-runtime-deps),
  and resolving the user from `item_id` alone. The webhook URL can be attached to an existing
  Item later, so deferring costs nothing.
- **Removing CSV import** — it is the only source of real data while Plaid is Sandbox-only, and
  afterwards the only way to backfill beyond Plaid's history window or bridge a broken connection.
- **Plaid Balance (real-time) and Assets (point-in-time report)** — Balance is billed per call and
  takes seconds; Assets is a lending product. The free cached balance covers "what's in the
  account as of the last sync". **Plaid Enrich** — only helps the CSV-imported rows (Plaid's own
  transactions arrive enriched), and is not among this account's enabled products; add-later.

### Consequences

- **"Zero runtime secrets" ends.** Architecture §4.3, the CLAUDE.md summary and the AWS-tooling
  note ("no Secrets Manager reads should ever be needed") are amended when this ADR is accepted.
  Agents still never fetch secret *values* into context.
- **New egress** to `sandbox.plaid.com`: transaction data now leaves AWS to a third party, the
  minimum the feature requires (NFR-4.6).
- **Sandbox data lands in the `dev` table next to the 153 real Chase rows** and will show up in
  dashboard totals. Every Plaid row is tagged with its source and Plaid environment so it can be
  purged by query before any Production Item is linked.
- **Dashboard figures are no longer all final.** `core/budgets.summarize` gains a pending
  amount per category and in the totals, and the dashboard and transaction list mark pending
  rows — a small, additive change to two things this ADR otherwise leaves alone. Pending is only
  as fresh as the last sync, and some banks (Capital One, USAA) report no pending at all.
- **"Sync now" is a stopgap, on the record.** Moving to webhooks is the named follow-up, not a
  silent default.
- **Deletes now happen without a per-row owner action** (`removed`). They are triggered by an
  owner-initiated sync, counted in the import report, and recoverable through PITR.
- **Open for the Production slice, deliberately not solved here:** the same real transaction
  arriving by CSV and by Plaid shares no key and would double-count (likely answer: a per-account
  cutover date, not fuzzy matching); Chase connects by OAuth, which needs a registered redirect
  URI and Plaid's Production prerequisites — long-lead owner tasks; history depth
  (`days_requested`) is fixed at first link; a CloudFront content-security policy (Slice 8) must
  allow `cdn.plaid.com`.
- Sandbox Items expire into a re-login state after about 30 days by design, so the reconnect
  ("update mode") path is unbuilt but will be needed for Production.

---

## ADR-015: Loan accounts stay out of spend; Plaid Sandbox data lives under its own user

**Status:** Accepted (2026-11-15, Slice 9 — owner decisions; recorded at slice wrap)

### Context

The first live Plaid Sandbox sync surfaced two problems ADR-014 had not decided.

1. **Loan payments read as income.** A loan account reports each payment as a *credit* (the
   balance owed went down). Counted like any other row, 46 Sandbox loan payments were filed as
   Income and netted spend down. The same payment also leaves checking, so once both sides are
   synced it would be counted twice. A credit-card payment from checking has the same shape.
2. **Sandbox rows were mixing with the owner's real rows.** ADR-014 accepted Sandbox data in the
   `dev` table next to the 153 real Chase rows, tagged for a later purge. In practice it put fake
   money into the owner's real cycle totals during the very slice meant to evaluate them.

### Decision

1. **Rows from accounts of Plaid type `loan` are left out of every dashboard figure.** The
   account type is stamped on each Plaid row at sync time (`accountType`) and is never removed by a
   later update, so the rule survives a disconnect and a closed account. The dashboard says how
   many rows it left out; loan balances stay visible on the Bank connections panel. Debt spending
   is counted once, where the cash leaves.
2. **A "Transfer" category (card payments, savings/CD moves) is deferred to Slice 7.**
3. **Plaid Sandbox data lives under a separate, dev-only Cognito user** (`PlaidSandboxUser`, a
   plus-address of the owner's email), isolated by the `USER#<sub>` partition (ADR-006). The
   Sandbox rows already in the owner's partition were deleted with an owner-approved, owner-run
   script (`backend/ops/purge_plaid_sandbox.py`: dry run by default, execution bound to a
   fingerprint of the exact keys the dry run listed, refused while a connection is linked).

### Alternatives considered

- **Count loan payments as debt spend.** Rejected: double-counts as soon as the checking side
  is synced.
- **Leave loan rows as they are.** Rejected: the dashboard's main figures are wrong.
- **A "hide Sandbox" filter on every read path.** Rejected: complexity spread across every
  query, for test data. **A separate `dev` stage or table** — rejected as heavier than a user.

### Consequences

- Dashboard totals no longer reconcile one-to-one with the transaction list; `excludedCount`
  and the dashboard note make the gap visible instead of silent.
- Rows written before `accountType` existed are not backfilled. The only such rows were the
  Sandbox rows this ADR deletes, so nothing needed a backfill.
- Transfers between the owner's own non-loan accounts still count as spend until Slice 7 (the
  `user_good` Sandbox persona shows card payments and CD deposits as its largest "spend").
  Plaid's `personal_finance_category` (which labels transfers and loan payments) is the natural
  input for that work.
- Nothing yet *stops* the owner linking a Sandbox bank while signed in as themselves; the
  separation is a convention backed by the purge tooling, not an enforced rule (backlog [B-11]).
- Production remains governed by ADR-014: a real bank would sync into the owner's own partition.

---

## ADR-016: Plaid Production on prod, on Plaid's free trial

**Status:** Proposed (2026-11-26, Slice 10). Becomes Accepted on the owner's word; nothing here is
deployed to prod before that.

### Context

The owner wants to manage real money in Ledgerly, which means linking real banks (Chase first).
ADR-014 kept Plaid on Sandbox and dev only, and said **no Production Item may be created until a
follow-up ADR records verified Plaid pricing against the $10/month ceiling (NFR-1.1)**. This is
that ADR.

Pricing, as the owner's Plaid Dashboard showed on 2026-11-26: the team is on Plaid's **free trial**,
"up to 10 connections", 0 of 10 used, Production keys issued, and "No action is needed to access
banks through Plaid's free trial". A connection is a Plaid Item (one bank login). Plaid's docs say
an Item removed with `/item/remove` **still counts** against the trial limit, and linking the same
bank twice uses two. Chase is an OAuth institution; on the trial it needs no extra registration.

dev cannot hold the real data: it is disposable by design (`retain_data=False`). prod is the
stage with retained data, deletion protection and a manual deploy gate.

### Decision

1. **prod talks to Plaid Production; dev stays on Sandbox.** `StageConfig.plaid_env` is
   `"production"` on prod, `"sandbox"` on dev, and `infra/check_plaid_environments.py` fails CI
   if any Lambda, secret name or host in either template points at the other environment. The
   backend accepts only those two values, and the Sandbox-only test calls refuse to run on a
   Production client.
2. **The free trial is the plan: up to 10 Items, $0.** That is the owner plus a few friends.
   Going past 10, or a trial that ends, needs a paid Plaid plan and a revision of NFR-1.1 first.
   Because a removed Item still uses a slot, the app warns before Disconnect, and re-linking is
   avoided where Reconnect (update mode) fixes the login.
3. **Bank OAuth return.** Link tokens carry `redirect_uri = {prod site}/oauth/plaid` (prod only,
   `plaid_oauth_redirect`), which the owner registers in the Plaid Dashboard. Desktop uses
   Plaid's popup and never needs it; a phone may leave the page for the bank and come back there,
   where the SPA reopens the same Link session with `receivedRedirectUri`. The Link token is kept
   in localStorage for that round trip only (cleared when Link finishes, ignored after an hour).
4. **Two years of history** (`transactions.days_requested = 730`) on every new Item. It is fixed
   when the Item is created, so it has to be right the first time.
5. **MFA is required** in both user pools (TOTP), since the app now holds live bank access.
6. **A Content-Security-Policy and security headers** on CloudFront (HSTS, nosniff, DENY framing,
   strict-origin referrer), allowing only this app, Cognito, the stage's API and upload hosts and,
   where Plaid is configured, Plaid Link's documented hosts.
7. **The access-token write race ([B-11]) is fixed** with a short DynamoDB lease
   (`adapters/locks.py`) around each read-modify-write of the tokens secret, since Secrets
   Manager has no compare-and-swap. A writer that waits more than 6 seconds gets a retryable 503;
   a crashed holder's lease expires after 20. A bank link waits twice, because its public token
   is already spent; if both waits fail it removes the new Item at Plaid rather than leave a
   live connection with no stored token (the slot is still used, per point 2).

### Alternatives considered

- **A paid plan now.** Rejected: nothing needs more than 10 Items yet, and per-Item monthly fees
  would take most of the ceiling.
- **Production on dev.** Rejected: dev's table is deleted with its stack, and real bank data does
  not belong next to Sandbox test users.
- **One secret per Item** instead of the lease. Rejected for now: $0.40/month per bank, and the
  IAM grant could no longer name one secret. The lease costs nothing.
- **CSP in Report-Only first.** Rejected: dev deploys first on merge and is checked in a browser
  before the owner approves prod, which is the same safety for less work.

### Consequences

- Real transaction data now leaves AWS to `production.plaid.com` (NFR-4.6, already accepted in
  principle by ADR-014). The owner's Production keys live in `ledgerly/prod/plaid/api-keys`,
  created by the owner by hand; the stack still only references it by name.
- prod gains the Plaid Lambdas and two secrets (about $0.80/month), so steady state is about
  $3-6/month, inside the ceiling.
- The same real transaction imported by CSV and synced by Plaid would count twice (ADR-014's open
  item). prod has no CSV history today, so the rule is: on prod, use Plaid for an account and do
  not CSV-import overlapping dates for it. A cutover date per account is the fix if that changes.
- Signing in now needs an authenticator app; the first sign-in after deploy asks to set one up.
- Transfers between own accounts still count as spend until the Transfer category lands (next PR).

---

<!-- Copy the ADR block above for each new decision. Keep them append-only. -->


## ADR-017: Transfers between own accounts, from Plaid's own label

**Status:** Proposed (2026-11-26, Slice 10). Becomes Accepted on the owner's word.

### Context

Paying a credit card from checking, or moving money to savings, is not spending, but it lands
in Ledgerly as two ordinary transactions and both were counted in the dashboard (backlog [B-11],
deferred to Slice 7 by ADR-015). With real accounts on Plaid Production (ADR-016) that would
double-count every card bill. Plaid already labels each transaction with
`personal_finance_category` (`primary`, `detailed`, `confidence_level`), and the sync worker
keeps that in the row's `raw` copy.

### Decision

1. **A system Transfers category**, id `transfers`, `kind: "transfer"`, created per user the first
   time one of their rows needs it (a conditional put, so it is never duplicated). It is a normal
   category the owner can rename or archive. Archived means "stop filing there": new rows go
   through the usual rules and model instead.
2. **Only Plaid's own label files a row there**, before merchant rules and the model, with no
   model call: `detailed` is one of `TRANSFER_IN/OUT_ACCOUNT_TRANSFER`,
   `TRANSFER_IN/OUT_SAVINGS` or `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`, **and** `confidence_level`
   is `HIGH` or `VERY_HIGH`, **and** no counterparty is a `payment_app` (Venmo, Zelle and the
   like are often a person, so they stay with the model). The model is never offered Transfers,
   so it cannot file a guess there.
3. **The dashboard leaves Transfers out**: no row, no budget (the API refuses one), not in the
   totals; it shows only how many transfers were set aside, so nothing vanishes silently.
4. **CSV rows are unchanged**: they carry no Plaid label, and the owner's real data is moving to
   Plaid. Investment contributions keep the existing "Savings & Investments" category.

### Alternatives considered

- **Let the model choose Transfers.** Rejected: a wrong guess hides real spending from every
  total, and Plaid's label is free and better informed (it sees both sides).
- **Match the two legs of a transfer ourselves** (same amount, opposite sign, close dates).
  Deferred: needs both accounts linked and a matching window; Plaid's label already covers the
  common cases.
- **Include person-to-person apps.** Rejected for now: paying a friend back for dinner is spending.

### Consequences

- Card payments and savings moves stop inflating spend on Plaid-linked accounts.
- A row Plaid labels wrongly, or at `MEDIUM` confidence, is still categorized by the model, and
  the owner can correct it once the review queue lands (Slice 7).
- Revisit if Plaid changes its taxonomy, or if CSV accounts come back into regular use.
