"""CategorizationConstruct — async AI categorization backbone (Slice 5, FR-3; ADR-008/009).

The categorization pipeline (architecture §3.2, §4.5): the import Lambda enqueues newly-added
transactions on an **SQS queue**; a **categorizer Lambda** consumes batches, applies merchant
rules then Claude Opus 4.8 on Amazon Bedrock, and writes each result back to the one table.
Decoupling via SQS keeps categorization off the import path (FR-3.5) and gives retries + a
**dead-letter queue** for free.

This construct owns the queue (+ DLQ + alarm), the categorizer Lambda, and its least-privilege
grants. **Zero runtime secrets** (ADR-008): the Lambda calls Bedrock and DynamoDB with its IAM
role — the Bedrock grant is scoped to the one model family it runs. The import Lambda (in
`IngestConstruct`) is granted send access + the queue URL separately, since it is the producer.
"""
from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from ledgerly.config import (
    BEDROCK_FOUNDATION_MODEL,
    BEDROCK_MODEL_ID,
    CONFIDENCE_THRESHOLD,
    StageConfig,
)

# repo-root/backend — the Lambda asset root (handler + core + adapters live here).
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"

_RETENTION = {
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}

# After 3 failed receives a message lands in the DLQ (architecture §4.5) with the transactions
# left Uncategorized (FR-3.5) — fix the cause, then redrive.
_MAX_RECEIVE_COUNT = 3


class CategorizationConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: StageConfig,
        table: ddb.ITable,
    ):
        super().__init__(scope, construct_id)

        self.dlq = sqs.Queue(
            self,
            "CategorizeDlq",
            queue_name=f"ledgerly-{stage.name}-categorize-dlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,  # SSE (architecture §4.4)
            enforce_ssl=True,
            retention_period=Duration.days(14),
        )
        self.queue = sqs.Queue(
            self,
            "CategorizeQueue",
            queue_name=f"ledgerly-{stage.name}-categorize",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            # Visibility must exceed the consumer's timeout so a slow batch isn't redelivered
            # while still processing (AWS guidance: ≥ the Lambda timeout).
            visibility_timeout=Duration.minutes(6),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=_MAX_RECEIVE_COUNT, queue=self.dlq),
        )

        log_group = logs.LogGroup(
            self,
            "CategorizerLogs",
            retention=_RETENTION.get(stage.log_retention_days, logs.RetentionDays.ONE_MONTH),
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.categorizer_fn = _lambda.Function(
            self,
            "CategorizerFn",
            function_name=f"ledgerly-{stage.name}-categorizer",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="functions.categorizer.handler.handler",
            code=_lambda.Code.from_asset(
                str(_BACKEND_DIR),
                exclude=["tests", "eval", "**/__pycache__", "**/*.pyc", "pyproject.toml", "*.md"],
            ),
            timeout=Duration.minutes(5),  # categorizer λ budget — Bedrock w/ retry (arch §4.6)
            memory_size=512,
            environment={
                "TABLE_NAME": table.table_name,
                "BEDROCK_MODEL_ID": BEDROCK_MODEL_ID,
                "CONFIDENCE_THRESHOLD": CONFIDENCE_THRESHOLD,
                "LOG_LEVEL": "INFO",
            },
            log_group=log_group,
            tracing=_lambda.Tracing.ACTIVE,
        )

        # SQS → Lambda. Partial-batch-failure reporting means a single bad message redelivers
        # alone (→ DLQ), not the whole batch (the handler returns batchItemFailures).
        self.categorizer_fn.add_event_source(
            sources.SqsEventSource(
                self.queue,
                batch_size=5,
                max_batching_window=Duration.seconds(20),
                report_batch_item_failures=True,
            )
        )

        # Least privilege: the categorizer reads/writes the one table and invokes exactly the
        # one Bedrock model family — nothing else, no `*` service access (NFR-4.4).
        table.grant_read_write_data(self.categorizer_fn)
        self.categorizer_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                # Opus 4.8 is INFERENCE_PROFILE-only, so invoking needs permission on BOTH the
                # inference-profile (in this region) AND the underlying foundation model in every
                # region the cross-region profile may route to (region wildcarded). Bounded to
                # the one model — no `*` model access (NFR-4.4).
                resources=[
                    f"arn:aws:bedrock:{stage.region}:{stage.account}:inference-profile/{BEDROCK_MODEL_ID}",
                    f"arn:aws:bedrock:*::foundation-model/{BEDROCK_FOUNDATION_MODEL}",
                ],
            )
        )

        # DLQ depth alarm (architecture §4.1): any message in the DLQ means categorizations are
        # failing and being lost to review — surface it. (No SNS action wired yet; the alarm is
        # the signal — an owner-facing notification target is a later Ops enhancement.)
        cloudwatch.Alarm(
            self,
            "CategorizeDlqAlarm",
            alarm_name=f"ledgerly-{stage.name}-categorize-dlq",
            alarm_description="Categorization DLQ has messages — a batch failed 3× (arch §4.5).",
            metric=self.dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(5), statistic="Maximum"
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
