#!/usr/bin/env python3
"""Ledgerly CDK app entrypoint.

One CDK app, one stack per stage (Ledgerly-dev, Ledgerly-prod), each composed of
constructs (architecture §5.1). Every stack is pinned to the dedicated Ledgerly AWS
account (ADR-010) via an explicit env — CDK refuses to deploy if the caller's
credentials resolve to a different account, which is a deploy-time account guard.
"""
import aws_cdk as cdk

from ledgerly.cicd_stack import LedgerlyCicdStack
from ledgerly.config import LEDGERLY_ACCOUNT, LEDGERLY_REGION, STAGES
from ledgerly.stack import LedgerlyStack

app = cdk.App()

# Account-global CI/CD identity (ADR-011) — one OIDC provider + deploy role for the account,
# deployed once by hand; the pipeline then uses it to deploy both stages below.
LedgerlyCicdStack(
    app,
    "Ledgerly-cicd",
    account=LEDGERLY_ACCOUNT,
    region=LEDGERLY_REGION,
    env=cdk.Environment(account=LEDGERLY_ACCOUNT, region=LEDGERLY_REGION),
    description="Ledgerly CI/CD — GitHub OIDC deploy federation (ADR-011)",
)

for stage in STAGES.values():
    LedgerlyStack(
        app,
        f"Ledgerly-{stage.name}",
        stage=stage,
        env=cdk.Environment(account=stage.account, region=stage.region),
        description=f"Ledgerly {stage.name} — personal budgeting app (single account, ADR-010)",
    )

app.synth()
