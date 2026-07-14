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
