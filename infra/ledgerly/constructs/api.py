"""ApiConstruct — HTTP API + Cognito JWT authorizer + the GET /settings Lambda (ADR-007).

Slice 1 exposes a single authenticated route. The JWT authorizer rejects absent/invalid
tokens with 401 *before* any Lambda runs (architecture §3.5). The Lambda gets least-
privilege: read/write on the one table only — nothing else, no `*` resources (NFR-4.4).
Business identity is read from the verified JWT claims inside the handler (FR-1.3).
"""
from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

from ledgerly.config import StageConfig

# repo-root/backend — the Lambda asset root (handler + core + adapters live here).
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"

_RETENTION = {
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}


class ApiConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: StageConfig,
        table: ddb.ITable,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        allowed_origins: list[str],
    ):
        super().__init__(scope, construct_id)

        log_group = logs.LogGroup(
            self,
            "SettingsFnLogs",
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )

        settings_fn = _lambda.Function(
            self,
            "SettingsFn",
            function_name=f"ledgerly-{stage.name}-api-settings",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.api_settings.handler.handler",
            code=_lambda.Code.from_asset(
                str(_BACKEND_DIR),
                exclude=["tests", "**/__pycache__", "**/*.pyc", "pyproject.toml", "*.md"],
            ),
            timeout=Duration.seconds(10),  # API λ budget (architecture §4.6)
            memory_size=256,
            environment={"TABLE_NAME": table.table_name, "LOG_LEVEL": "INFO"},
            log_group=log_group,
            tracing=_lambda.Tracing.ACTIVE,
        )
        # Least privilege: this Lambda touches exactly one table, read + write (AP #1 creates
        # the PROFILE item on first call). No other grants.
        table.grant_read_write_data(settings_fn)

        authorizer = authorizers.HttpUserPoolAuthorizer(
            "SettingsAuthorizer",
            user_pool,
            user_pool_clients=[user_pool_client],
        )

        self.http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"ledgerly-{stage.name}",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=allowed_origins,  # explicit origins — never "*"
                allow_methods=[apigwv2.CorsHttpMethod.GET, apigwv2.CorsHttpMethod.OPTIONS],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.days(1),
            ),
        )
        self.http_api.add_routes(
            path="/settings",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("SettingsIntegration", settings_fn),
            authorizer=authorizer,
        )

    @property
    def api_url(self) -> str:
        return self.http_api.api_endpoint
