"""ApiConstruct — HTTP API + Cognito JWT authorizer + the application Lambdas (ADR-007).

Routes (all behind the JWT authorizer, which rejects absent/invalid tokens with 401 *before*
any Lambda runs — architecture §3.5):
  GET/PATCH /settings        → settings Lambda (cadence config + live current cycle, FR-4.2)
  GET/POST  /categories      → categories Lambda (list/create, FR-4.1/4.4)
  PATCH     /categories/{id} → categories Lambda (rename/archive, FR-4.1)
  GET/POST  /imports         → imports Lambda (presigned upload + recent imports, FR-2.5)
  GET       /imports/{id}    → imports Lambda (status polling, FR-2.5)
  GET       /transactions    → transactions Lambda (date-window list, FR-2 / AP 6)

Each Lambda gets least privilege: read/write on the one table only — nothing else, no `*`
resources (NFR-4.4). The imports Lambda additionally gets `s3:PutObject` on the upload bucket
so the presigned URLs it mints are usable. Business identity is read from the verified JWT
claims inside each handler (FR-1.3).
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
from aws_cdk import aws_s3 as s3
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
        upload_bucket: s3.IBucket,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        allowed_origins: list[str],
    ):
        super().__init__(scope, construct_id)

        settings_fn = self._api_lambda(
            "SettingsFn",
            stage=stage,
            table=table,
            function_name=f"ledgerly-{stage.name}-api-settings",
            handler="functions.api_settings.handler.handler",
        )
        categories_fn = self._api_lambda(
            "CategoriesFn",
            stage=stage,
            table=table,
            function_name=f"ledgerly-{stage.name}-api-categories",
            handler="functions.api_categories.handler.handler",
        )
        transactions_fn = self._api_lambda(
            "TransactionsFn",
            stage=stage,
            table=table,
            function_name=f"ledgerly-{stage.name}-api-transactions",
            handler="functions.api_transactions.handler.handler",
        )
        imports_fn = self._api_lambda(
            "ImportsFn",
            stage=stage,
            table=table,
            function_name=f"ledgerly-{stage.name}-api-imports",
            handler="functions.api_imports.handler.handler",
            extra_env={"UPLOAD_BUCKET": upload_bucket.bucket_name},
        )
        # The presigned PUT URL is signed with this Lambda's role, so the role must be able to
        # write the object the browser uploads (least privilege: put only, no read).
        upload_bucket.grant_put(imports_fn)

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
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PATCH,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.days(1),
            ),
        )
        self.http_api.add_routes(
            path="/settings",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PATCH],
            integration=integrations.HttpLambdaIntegration("SettingsIntegration", settings_fn),
            authorizer=authorizer,
        )
        self.http_api.add_routes(
            path="/categories",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("CategoriesIntegration", categories_fn),
            authorizer=authorizer,
        )
        self.http_api.add_routes(
            path="/categories/{id}",
            methods=[apigwv2.HttpMethod.PATCH],
            integration=integrations.HttpLambdaIntegration(
                "CategoriesItemIntegration", categories_fn
            ),
            authorizer=authorizer,
        )
        self.http_api.add_routes(
            path="/imports",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("ImportsIntegration", imports_fn),
            authorizer=authorizer,
        )
        self.http_api.add_routes(
            path="/imports/{id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("ImportsItemIntegration", imports_fn),
            authorizer=authorizer,
        )
        self.http_api.add_routes(
            path="/transactions",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration(
                "TransactionsIntegration", transactions_fn
            ),
            authorizer=authorizer,
        )

    def _api_lambda(
        self,
        construct_id: str,
        *,
        stage: StageConfig,
        table: ddb.ITable,
        function_name: str,
        handler: str,
        extra_env: dict[str, str] | None = None,
    ) -> _lambda.Function:
        """A least-privilege API Lambda: read/write on the one table, nothing else (NFR-4.4)."""
        log_group = logs.LogGroup(
            self,
            f"{construct_id}Logs",
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )
        fn = _lambda.Function(
            self,
            construct_id,
            function_name=function_name,
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler=handler,
            code=_lambda.Code.from_asset(
                str(_BACKEND_DIR),
                exclude=["tests", "**/__pycache__", "**/*.pyc", "pyproject.toml", "*.md"],
            ),
            timeout=Duration.seconds(10),  # API λ budget (architecture §4.6)
            memory_size=256,
            environment={"TABLE_NAME": table.table_name, "LOG_LEVEL": "INFO", **(extra_env or {})},
            log_group=log_group,
            tracing=_lambda.Tracing.ACTIVE,
        )
        table.grant_read_write_data(fn)
        return fn

    @property
    def api_url(self) -> str:
        return self.http_api.api_endpoint
