"""LedgerlyCicdStack — account-global CI/CD identity, deployed once (ADR-011).

Separate from the per-stage `LedgerlyStack` because its resources (the GitHub OIDC provider
and the shared deploy role) are account-scoped, not per-stage — one exists for the whole
account and is used to deploy *both* `dev` and `prod`. Like `cdk bootstrap`, this stack is
deployed manually once from an authenticated workstation; thereafter the pipeline assumes the
role it creates. Pinned to the dedicated Ledgerly account (ADR-010) via an explicit env.
"""
from aws_cdk import CfnOutput, Stack
from constructs import Construct

from ledgerly.constructs.cicd import CicdConstruct


class LedgerlyCicdStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, account: str, region: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        cicd = CicdConstruct(self, "Cicd", account=account, region=region)

        CfnOutput(self, "DeployRoleArn", value=cicd.deploy_role.role_arn)
