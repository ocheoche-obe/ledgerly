"""DataConstruct — the single DynamoDB table (ADR-005) with its full key schema.

The full key design ships day one (architecture §2.4): base table `pk`/`sk` plus GSI1
(category drill-down) and GSI2 (sparse review queue). Adding GSIs to an existing table is a
slow online operation, so we pay the (zero) cost of defining them now and avoid a migration
later. Slice 1 only reads/writes the PROFILE item, but the schema is complete.
"""
from aws_cdk import RemovalPolicy
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct

from ledgerly.config import StageConfig

_STRING = ddb.AttributeType.STRING


class DataConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig):
        super().__init__(scope, construct_id)

        self.table = ddb.Table(
            self,
            "Table",
            table_name=f"ledgerly-{stage.name}",
            partition_key=ddb.Attribute(name="pk", type=_STRING),
            sort_key=ddb.Attribute(name="sk", type=_STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,  # on-demand — ~$0 idle (ADR-005)
            # SSE with AWS-owned keys is the default (architecture §4.4) — no KMS cost.
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True  # NFR-3.1 no data loss
            ),
            deletion_protection=stage.retain_data,
            removal_policy=RemovalPolicy.RETAIN if stage.retain_data else RemovalPolicy.DESTROY,
        )

        # GSI1 — category drill-down (AP 8): USER#<sub>#CAT#<catId> / TXN#<date>#<txnId>.
        self.table.add_global_secondary_index(
            index_name="gsi1",
            partition_key=ddb.Attribute(name="gsi1pk", type=_STRING),
            sort_key=ddb.Attribute(name="gsi1sk", type=_STRING),
        )

        # GSI2 — review queue (AP 9), sparse: keys present only while needsReview is true.
        self.table.add_global_secondary_index(
            index_name="gsi2",
            partition_key=ddb.Attribute(name="gsi2pk", type=_STRING),
            sort_key=ddb.Attribute(name="gsi2sk", type=_STRING),
        )
