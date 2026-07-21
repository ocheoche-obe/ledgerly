"""IngestConstruct — CSV upload bucket + S3-triggered import Lambda (Slice 4, FR-2).

The write path (architecture §2.3, §3.1): the browser uploads a bank CSV straight to a
private S3 bucket via a presigned PUT (minted by the /imports API Lambda) — the file never
transits Lambda. S3 then fires an `ObjectCreated` event that triggers the import Lambda,
which parses, normalizes, and idempotently persists transactions to the one table.

The bucket is transport only: the normalized transactions *and* their raw source rows live
in DynamoDB (FR-2.4), so uploaded objects are expired after a short window to bound cost and
minimize how long raw financial data sits in S3. After persisting, the importer enqueues the
newly-added rows onto the categorization queue (owned by `CategorizationConstruct`, Slice 5) —
this construct is the *producer* (send-only); the consumer + queue live there.
"""
from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from ledgerly.config import StageConfig

# repo-root/backend — the Lambda asset root (handler + core + adapters live here).
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"

_RETENTION = {
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}

# Raw uploads are transient (the data is persisted to DynamoDB, FR-2.4); expire the S3 copy
# to bound cost and limit how long raw financial data lingers.
_UPLOAD_EXPIRY_DAYS = 30


class IngestConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: StageConfig,
        table: ddb.ITable,
        categorize_queue: sqs.IQueue,
        allowed_origins: list[str],
    ):
        super().__init__(scope, construct_id)

        self.bucket = s3.Bucket(
            self,
            "UploadBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,  # SSE-S3 (architecture §4.4)
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN if stage.retain_data else RemovalPolicy.DESTROY,
            auto_delete_objects=not stage.retain_data,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(_UPLOAD_EXPIRY_DAYS))],
            # The browser PUTs the file via a presigned URL, so the bucket must allow that
            # cross-origin PUT from the SPA origin(s) — never "*".
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=allowed_origins,
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

        log_group = logs.LogGroup(
            self,
            "ImporterLogs",
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.importer_fn = _lambda.Function(
            self,
            "ImporterFn",
            function_name=f"ledgerly-{stage.name}-importer",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.importer.handler.handler",
            code=_lambda.Code.from_asset(
                str(_BACKEND_DIR),
                exclude=["tests", "eval", "**/__pycache__", "**/*.pyc", "pyproject.toml", "*.md"],
            ),
            timeout=Duration.minutes(2),  # import λ budget (architecture §4.6)
            memory_size=512,
            environment={
                "TABLE_NAME": table.table_name,
                "UPLOAD_BUCKET": self.bucket.bucket_name,
                # The importer enqueues newly-added rows for async categorization (FR-3, Slice 5).
                "CATEGORIZE_QUEUE_URL": categorize_queue.queue_url,
                "LOG_LEVEL": "INFO",
            },
            log_group=log_group,
            tracing=_lambda.Tracing.ACTIVE,
        )
        # Least privilege: the importer reads uploaded objects, writes the one table, and sends
        # categorization jobs to the queue (nothing consumes from it here — that's the
        # categorizer's role).
        self.bucket.grant_read(self.importer_fn)
        table.grant_read_write_data(self.importer_fn)
        categorize_queue.grant_send_messages(self.importer_fn)

        # S3 → Lambda on new .csv uploads. Keys are `<sub>/<importId>.csv`.
        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.importer_fn),
            s3.NotificationKeyFilter(suffix=".csv"),
        )
