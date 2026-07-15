"""LedgerlyStack — one stack per stage, composed of constructs (architecture §5.1).

Slice 1 (walking skeleton) wires five of the seven planned constructs: Data, Auth, Api,
Web, Ops. Ingest and Categorization arrive in their own slices (4 and 5).

Construct order matters — it keeps CloudFormation dependencies acyclic:
  Data → Web(bucket+CDN) → Auth(callback URLs need the site URL) → Api(needs Auth+Data)
  → Web.deploy_spa(runtime config needs Auth+Api) → Ops.
"""
import aws_cdk as cdk
from aws_cdk import Stack
from constructs import Construct

from ledgerly.config import StageConfig
from ledgerly.constructs.api import ApiConstruct
from ledgerly.constructs.auth import AuthConstruct
from ledgerly.constructs.data import DataConstruct
from ledgerly.constructs.ops import OpsConstruct
from ledgerly.constructs.web import WebConstruct


class LedgerlyStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig, **kwargs):
        super().__init__(
            scope,
            construct_id,
            termination_protection=stage.termination_protection,
            **kwargs,
        )

        data = DataConstruct(self, "Data", stage=stage)
        web = WebConstruct(self, "Web", stage=stage)
        auth = AuthConstruct(self, "Auth", stage=stage, site_url=web.site_url)
        # CORS: the deployed site always; the local dev SPA origin only in dev (prod must not
        # accept requests from a developer's localhost).
        allowed_origins = [web.site_url]
        if stage.name == "dev":
            allowed_origins.append("http://localhost:5173")
        api = ApiConstruct(
            self,
            "Api",
            stage=stage,
            table=data.table,
            user_pool=auth.user_pool,
            user_pool_client=auth.user_pool_client,
            allowed_origins=allowed_origins,
        )
        # Single BucketDeployment: SPA assets + runtime config.json (needs Auth + Api values).
        web.deploy_spa(
            region=stage.region,
            user_pool_id=auth.user_pool.user_pool_id,
            user_pool_client_id=auth.user_pool_client.user_pool_client_id,
            cognito_domain=auth.hosted_ui_base_url,
            api_url=api.api_url,
        )
        OpsConstruct(self, "Ops", stage=stage)

        cdk.CfnOutput(self, "SiteUrl", value=web.site_url)
        cdk.CfnOutput(self, "ApiUrl", value=api.api_url)
        cdk.CfnOutput(self, "HostedUiUrl", value=auth.hosted_ui_base_url)
        cdk.CfnOutput(self, "UserPoolId", value=auth.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=auth.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "TableName", value=data.table.table_name)
