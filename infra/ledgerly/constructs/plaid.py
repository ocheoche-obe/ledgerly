"""PlaidConstruct — Plaid bank ingest (Slice 9, ADR-014; prod added by ADR-016).

dev talks to Plaid Sandbox and prod to Plaid Production (`StageConfig.plaid_env`). Owns
everything Plaid-specific, so a stage with no Plaid environment synthesizes with none of it:
three Lambdas and Ledgerly's only two runtime secrets.

- **`api_fn`** — `POST /plaid/link-token`, `/plaid/exchange`, `/plaid/sync` (routes are wired
  by `ApiConstruct`, behind the same JWT authorizer as everything else).
- **`sync_fn`** — the worker that pages `/transactions/sync` and writes transactions. Invoked
  asynchronously by `api_fn`, so a slow first sync is not bound by API Gateway's 30 seconds.

- **`sync_failed_fn`** — the worker's on-failure destination: marks an import `failed` when
  the worker timed out or crashed on both attempts and so could not report it itself.

**Secrets (NFR-4.3/4.5).** Lambdas receive secret *names* in their environment, never values.

- *Plaid API keys* — **not created here.** The owner creates the secret by hand; the stack
  only refers to it by name to scope IAM. Its value therefore never exists in CDK, a
  CloudFormation template, the repo, or CI. Until it exists the Lambdas deploy fine and every
  Plaid call fails with a clear "not configured" error.
- *Plaid access tokens* — created here, empty, and written at runtime by `api_fn` alone.

Least privilege (NFR-4.4): the worker can read both secrets and write neither; only `api_fn`
can write the token secret, and only with `PutSecretValue`; `sync_failed_fn` has table access
and no secret access; nothing else in the stack can read either secret.
"""

from aws_cdk import Duration, RemovalPolicy, SecretValue
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from ledgerly.backend_asset import backend_code
from ledgerly.config import PLAID_OAUTH_REDIRECT_PATH, StageConfig

_RETENTION = {
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}


def plaid_keys_secret_name(stage_name: str) -> str:
    """The owner-created secret holding `{"client_id": ..., "secret": ...}`."""
    return f"ledgerly/{stage_name}/plaid/api-keys"


def plaid_tokens_secret_name(stage_name: str) -> str:
    return f"ledgerly/{stage_name}/plaid/access-tokens"


class PlaidConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: StageConfig,
        table: ddb.ITable,
        categorize_queue: sqs.IQueue,
        site_url: str,
    ):
        super().__init__(scope, construct_id)
        if stage.plaid_env is None:
            raise ValueError(f"stage {stage.name!r} has no Plaid environment configured")

        # Referenced by name only — see the module docstring. `from_secret_name_v2` scopes the
        # grant to this one secret name (plus the random suffix Secrets Manager appends).
        keys_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "ApiKeys", plaid_keys_secret_name(stage.name)
        )

        tokens_secret = secretsmanager.Secret(
            self,
            "AccessTokens",
            secret_name=plaid_tokens_secret_name(stage.name),
            description="Ledgerly - Plaid access tokens per linked Item, written by the "
            "api-plaid Lambda (ADR-014). Do not edit by hand.",
            # An empty document, not a secret: this literal is the *initial* value only.
            # CloudFormation rewrites a secret's value only when this property changes, so
            # leave it alone — changing it would replace every stored access token.
            secret_string_value=SecretValue.unsafe_plain_text('{"items":{}}'),
            removal_policy=RemovalPolicy.DESTROY if not stage.retain_data else RemovalPolicy.RETAIN,
        )

        common_env = {
            "TABLE_NAME": table.table_name,
            "LOG_LEVEL": "INFO",
            "PLAID_ENV": stage.plaid_env,
            "PLAID_KEYS_SECRET_ID": keys_secret.secret_name,
            "PLAID_TOKENS_SECRET_ID": tokens_secret.secret_name,
        }

        # Table access only, and no Plaid or secret configuration at all.
        self.sync_failed_fn = _lambda.Function(
            self,
            "SyncFailedFn",
            function_name=f"ledgerly-{stage.name}-plaid-sync-failed",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.plaid_sync.on_failure.handler",
            code=backend_code(),
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={"TABLE_NAME": table.table_name, "LOG_LEVEL": "INFO"},
            log_group=self._log_group("SyncFailedLogs", stage),
        )
        table.grant_read_write_data(self.sync_failed_fn)

        self.sync_fn = _lambda.Function(
            self,
            "SyncFn",
            function_name=f"ledgerly-{stage.name}-plaid-sync",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.plaid_sync.handler.handler",
            code=backend_code(),
            # A first sync pages up to two years of history, and Plaid notes it can be several
            # times slower than a routine call.
            timeout=Duration.minutes(3),
            memory_size=512,
            environment={**common_env, "CATEGORIZE_QUEUE_URL": categorize_queue.queue_url},
            log_group=self._log_group("SyncLogs", stage),
            tracing=_lambda.Tracing.ACTIVE,
        )
        # A sync is idempotent, so one automatic retry after a crash or timeout is safe — and
        # is what finishes a run that died between its writes and saving the cursor.
        # If the retry dies too, the import must not be left "parsing" forever: the original
        # event goes to `sync_failed_fn`, which marks it failed.
        self.sync_fn.configure_async_invoke(
            retry_attempts=1,
            max_event_age=Duration.minutes(15),
            on_failure=destinations.LambdaDestination(self.sync_failed_fn),
        )
        table.grant_read_write_data(self.sync_fn)
        categorize_queue.grant_send_messages(self.sync_fn)
        keys_secret.grant_read(self.sync_fn)
        tokens_secret.grant_read(self.sync_fn)

        self.api_fn = _lambda.Function(
            self,
            "ApiFn",
            function_name=f"ledgerly-{stage.name}-api-plaid",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.api_plaid.handler.handler",
            code=backend_code(),
            # Longer than the other API Lambdas' 10 s: the exchange makes two Plaid calls and
            # two Secrets Manager calls. Still inside API Gateway's 30 s integration limit.
            timeout=Duration.seconds(25),
            memory_size=256,
            environment={
                **common_env,
                "PLAID_SYNC_FUNCTION_NAME": self.sync_fn.function_name,
                # Only where the owner registered it with Plaid (see StageConfig).
                **({"PLAID_REDIRECT_URI": f"{site_url}{PLAID_OAUTH_REDIRECT_PATH}"}
                   if stage.plaid_oauth_redirect else {}),
            },
            log_group=self._log_group("ApiLogs", stage),
            tracing=_lambda.Tracing.ACTIVE,
        )
        table.grant_read_write_data(self.api_fn)
        keys_secret.grant_read(self.api_fn)
        tokens_secret.grant_read(self.api_fn)
        # Not `grant_write`: that also allows UpdateSecret (which can change the secret's KMS
        # key and description) and UpdateSecretVersionStage. Storing a token is one call.
        self.api_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["secretsmanager:PutSecretValue"],
            resources=[tokens_secret.secret_arn],
        ))
        self.sync_fn.grant_invoke(self.api_fn)

    def _log_group(self, construct_id: str, stage: StageConfig) -> logs.LogGroup:
        return logs.LogGroup(
            self,
            construct_id,
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )
