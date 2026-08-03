"""Per-stage configuration (architecture §5.3).

One AWS account (ADR-010); stages differ only by resource-name suffix and a handful of
posture knobs (log retention, deletion/termination protection, alarm cost). Hardcoding the
account here is deliberate: `app.py` feeds it to `cdk.Environment`, so a `cdk deploy` whose
credentials point at any other account (e.g. CareerVault, 768396678224) fails fast rather
than provisioning into the wrong place.
"""
from dataclasses import dataclass

# Dedicated Ledgerly account + region (ADR-010, architecture §0.1). Not a secret.
LEDGERLY_ACCOUNT = "816020558700"
LEDGERLY_REGION = "us-east-1"

# Billing alarm thresholds (NFR-1.2): alert at $5 actual / $8 forecast against the
# $10/month ceiling (NFR-1.1). Both stages carry it; the account bill is Ledgerly's spend.
BUDGET_ACTUAL_USD = 5
BUDGET_FORECAST_USD = 8

# Owner contact for budget alerts. Sourced from the session context; change here if it moves.
OWNER_EMAIL = "oche.ocheobe@gmail.com"

# AI categorization (Slice 5, ADR-008 as amended 2026-08-03). Config flows to the categorizer
# Lambda as env vars, and the model ids also scope the Bedrock IAM grant — kept here so runtime
# config and the least-privilege policy share one source. Switching the model is a change here
# + a redeploy, not a rewrite (the Categorizer interface is provider-agnostic) — a claim now
# actually exercised, since the original choice had to be swapped out.
#
# These are **INFERENCE_PROFILE-only** on Bedrock, so `invoke_model` must target the
# inference-profile id (`us.anthropic.…`), not the bare foundation-model id. The grant needs
# BOTH the profile ARN and the underlying foundation-model ARN (cross-region inference fans
# out to sibling regions: us-east-1, us-east-2, us-west-2).
#
# ⚠ Model choice is INTERIM. ADR-008 chose Opus 4.8; this account cannot invoke it. Live-tested
# 2026-08-03 — accepting the Bedrock model agreement does NOT unlock it, so this is account-tier
# eligibility, not a missing agreement. The boundary measured on account 816020558700:
#     invocable:  Haiku 4.5 · Sonnet 4.5 · Sonnet 4.6
#     denied:     Opus 4.7 · Opus 4.8 · Sonnet 5   (AccessDeniedException, agreements accepted)
# Sonnet 4.6 is the strongest model available. Revisit → Sonnet 5 when the owner's eligibility
# request lands; that is a two-line change here plus a redeploy.
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"        # what invoke_model targets
BEDROCK_FOUNDATION_MODEL = "anthropic.claude-sonnet-4-6"   # underlying FM, for the IAM grant
CONFIDENCE_THRESHOLD = "0.8"


@dataclass(frozen=True)
class StageConfig:
    name: str
    account: str
    region: str
    # Data-layer durability posture.
    retain_data: bool          # RETAIN removal policy + deletion protection on the table
    # CloudWatch log retention (days) — bounded cost (architecture §4.7).
    log_retention_days: int
    # CloudFormation stack termination protection.
    termination_protection: bool


STAGES: dict[str, StageConfig] = {
    "dev": StageConfig(
        name="dev",
        account=LEDGERLY_ACCOUNT,
        region=LEDGERLY_REGION,
        retain_data=False,          # dev is disposable; recreate freely
        log_retention_days=30,
        termination_protection=False,
    ),
    "prod": StageConfig(
        name="prod",
        account=LEDGERLY_ACCOUNT,
        region=LEDGERLY_REGION,
        retain_data=True,           # the owner's real data — never auto-deleted
        log_retention_days=90,
        termination_protection=True,
    ),
}
