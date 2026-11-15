"""PlaidConstruct — Plaid Sandbox ingest (Slice 9, ADR-014). Instantiated for `dev` only.

Owns everything Plaid-specific so that a stage without Plaid (prod) synthesizes with none of
it: two Lambdas and Ledgerly's first two runtime secrets.

- **`api_fn`** — `POST /plaid/link-token`, `/plaid/exchange`, `/plaid/sync` (routes are wired
  by `ApiConstruct`, behind the same JWT authorizer as everything else).
- **`sync_fn`** — the worker that pages `/transactions/sync` and writes transactions. Invoked
  asynchronously by `api_fn`, so a slow first sync is not bound by API Gateway's 30 seconds.

**Secrets (NFR-4.3/4.5).** Lambdas receive secret *names* in their environment, never values.

- *Plaid API keys* — **not created here.** The owner creates the secret by hand; the stack
  only refers to it by name to scope IAM. Its value therefore never exists in CDK, a
  CloudFormation template, the repo, or CI. Until it exists the Lambdas deploy fine and every
  Plaid call fails with a clear "not configured" error.
- *Plaid access tokens* — created here, empty, and written at runtime by `api_fn` alone.

Least privilege (NFR-4.4): the worker can read both secrets and write neither; only `api_fn`
can write the token secret; nothing else in the stack can read either.
"""

from aws_cdk import Duration, RemovalPolicy, SecretValue
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from ledgerly.backend_asset import backend_code
from ledgerly.config import StageConfig

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
        self.sync_fn.configure_async_invoke(
            retry_attempts=1, max_event_age=Duration.minutes(15)
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
            },
            log_group=self._log_group("ApiLogs", stage),
            tracing=_lambda.Tracing.ACTIVE,
        )
        table.grant_read_write_data(self.api_fn)
        keys_secret.grant_read(self.api_fn)
        tokens_secret.grant_read(self.api_fn)
        tokens_secret.grant_write(self.api_fn)
        self.sync_fn.grant_invoke(self.api_fn)

    def _log_group(self, construct_id: str, stage: StageConfig) -> logs.LogGroup:
        return logs.LogGroup(
            self,
            construct_id,
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )
