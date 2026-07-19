# Ledgerly — Architectural Decisions Log (ADL)

**Status:** Living document — updated as decisions are made
**Last updated:** 2026-07-19

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
| ADR-008 | AI categorization: Amazon Bedrock + Claude Opus 4.8, swappable interface | Accepted |
| ADR-009 | Async backbone: SQS queue + DLQ for categorization | Accepted |
| ADR-010 | AWS account topology: dedicated account per project | Accepted |
| ADR-011 | CI/CD deploy federation: GitHub OIDC assuming CDK bootstrap roles | Accepted |
| ADR-012 | Transaction natural key includes the running balance | Accepted |
| ADR-013 | Per-file account identity supplied (and confirmed) at upload time | Accepted |

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

## ADR-008: AI categorization — Amazon Bedrock + Claude Opus 4.8, behind a swappable interface

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

<!-- Copy the ADR block above for each new decision. Keep them append-only. -->
