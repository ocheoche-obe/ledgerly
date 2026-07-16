"""CicdConstruct — GitHub Actions OIDC federation into a narrow deploy role (ADR-011).

No long-lived AWS keys live in GitHub (NFR-4.3 in spirit). GitHub Actions presents an OIDC
token; AWS trusts it via an OpenID Connect provider, and the workflow assumes a role whose
*only* permission is `sts:AssumeRole` on the CDK bootstrap roles. The broad
CloudFormation/service rights stay in the bootstrap `cfn-exec-role` that CloudFormation uses
— never in this internet-reachable federated identity.

Account-global by nature (one OIDC provider per account, one shared deploy role for both
stages), so this lives in its own stage-less stack deployed once, like `cdk bootstrap`.
"""
from aws_cdk import Duration
from aws_cdk import aws_iam as iam
from constructs import Construct

# The repository whose workflows may assume the deploy role. Not a secret.
GITHUB_REPO = "ocheoche-obe/ledgerly"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_AUD = "sts.amazonaws.com"

# Fixed role name so the deploy workflow can reference a deterministic ARN.
DEPLOY_ROLE_NAME = "ledgerly-github-deploy"


class CicdConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        account: str,
        region: str,
    ):
        super().__init__(scope, construct_id)

        provider = iam.OpenIdConnectProvider(
            self,
            "GithubOidcProvider",
            url=GITHUB_OIDC_URL,
            client_ids=[GITHUB_OIDC_AUD],
        )

        # Trust only two subjects: the dev auto-deploy (push to main) and the prod job (which
        # runs in the `prod` GitHub Environment). A PR branch or fork cannot assume this role.
        allowed_subs = [
            f"repo:{GITHUB_REPO}:ref:refs/heads/main",
            f"repo:{GITHUB_REPO}:environment:prod",
        ]
        principal = iam.OpenIdConnectPrincipal(
            provider,
            conditions={
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": GITHUB_OIDC_AUD,
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": allowed_subs,
                },
            },
        )

        self.deploy_role = iam.Role(
            self,
            "GithubDeployRole",
            role_name=DEPLOY_ROLE_NAME,
            assumed_by=principal,
            description="GitHub Actions assumes this to run cdk deploy (ADR-011).",
            max_session_duration=Duration.hours(1),
        )

        # The role's only power: assume the CDK bootstrap roles. `cdk deploy` uses the
        # deploy/file-publishing/lookup roles; CloudFormation uses the cfn-exec role. All of
        # them match the default `hnb659fds` qualifier this account was bootstrapped with.
        # `sts:TagSession` alongside AssumeRole: the CDK CLI may attach session tags when it
        # assumes the bootstrap roles, and the bootstrap trust policy permits it.
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                actions=["sts:AssumeRole", "sts:TagSession"],
                resources=[
                    f"arn:aws:iam::{account}:role/cdk-hnb659fds-*-{account}-{region}",
                ],
            )
        )
