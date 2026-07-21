"""Integration tests for the import Lambda (functions/importer) against moto S3 + DynamoDB.

This is the strongest proof of the Slice-4 exit criteria: re-uploading the same file adds
zero duplicates, overlapping exports dedupe, malformed rows are counted (not fatal), and the
import report reflects reality. It drives the real flow — S3 object → importer → conditional
puts — with only AWS mocked. All CSV text is synthetic (no real transactions).
"""
from __future__ import annotations

import importlib
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"
BUCKET = "ledgerly-uploads-test"
HEADER = "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #"

# Full monthly export.
FILE_A = "\n".join([
    HEADER,
    'DEBIT,07/01/2026,"COFFEE A",-5.00,DEBIT_CARD,100.00,,',
    'DEBIT,07/02/2026,"LUNCH B",-10.00,DEBIT_CARD,90.00,,',
    'DEBIT,07/03/2026,"BOOK C",-15.00,DEBIT_CARD,75.00,,',
    'DEBIT,07/04/2026,"GAS D",-20.00,DEBIT_CARD,55.00,,',
    'DEBIT,07/05/2026,"FOOD E",-25.00,DEBIT_CARD,30.00,,',
]) + "\n"

# Month-to-date export overlapping FILE_A on 07/03–07/05, plus one new row (07/06). The
# overlapping rows are byte-identical in the natural-key fields (incl. balance), as real
# re-exports are.
FILE_B = "\n".join([
    HEADER,
    'DEBIT,07/03/2026,"BOOK C",-15.00,DEBIT_CARD,75.00,,',
    'DEBIT,07/04/2026,"GAS D",-20.00,DEBIT_CARD,55.00,,',
    'DEBIT,07/05/2026,"FOOD E",-25.00,DEBIT_CARD,30.00,,',
    'DEBIT,07/06/2026,"NEW F",-30.00,DEBIT_CARD,5.00,,',
]) + "\n"

# Three legitimately-distinct identical charges on one day (differ only by balance) + a
# malformed row that must be counted, not fatal.
FILE_MIXED = "\n".join([
    HEADER,
    'DEBIT,06/29/2026,"MIRRA VR         06/29",-31.76,DEBIT_CARD,3285.11,,',
    'DEBIT,06/29/2026,"MIRRA VR         06/29",-31.76,DEBIT_CARD,3316.87,,',
    'DEBIT,06/29/2026,"MIRRA VR         06/29",-31.76,DEBIT_CARD,3348.63,,',
    'DEBIT,99/99/2026,"BROKEN ROW",-1.00,DEBIT_CARD,1.00,,',
]) + "\n"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("UPLOAD_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        queue_url = boto3.client("sqs", region_name="us-east-1").create_queue(
            QueueName="ledgerly-categorize-test"
        )["QueueUrl"]
        monkeypatch.setenv("CATEGORIZE_QUEUE_URL", queue_url)
        for mod in ("adapters.dynamo", "adapters.s3", "adapters.sqs", "functions.importer.handler"):
            sys.modules.pop(mod, None)
        dynamo = importlib.import_module("adapters.dynamo")
        s3 = importlib.import_module("adapters.s3")
        importer = importlib.import_module("functions.importer.handler")
        yield _Env(dynamo, s3, importer, queue_url)


class _Env:
    def __init__(self, dynamo, s3, importer, queue_url):
        self.dynamo = dynamo
        self.s3 = s3
        self.importer = importer
        self.queue_url = queue_url

    def drain_queue(self) -> list[dict]:
        """All enqueued categorization messages, parsed — proves the import→categorize seam."""
        sqs = boto3.client("sqs", region_name="us-east-1")
        msgs: list[dict] = []
        while True:
            resp = sqs.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=10)
            batch = resp.get("Messages", [])
            if not batch:
                return msgs
            for m in batch:
                import json as _json
                msgs.append(_json.loads(m["Body"]))
                sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"])

    def start_import(self, sub, content, *, account_label="Chase 5980", import_id=None):
        """Create an import record, put the object in S3, and return (import_id, event)."""
        from core.accounts import normalize_account_id
        from core.ids import new_ulid

        import_id = import_id or new_ulid()
        key = self.s3.upload_key(sub, import_id)
        self.dynamo.create_import(
            sub, import_id, filename="export.csv", account_label=account_label,
            account_id=normalize_account_id(account_label), object_key=key,
            created_at="2026-07-19T00:00:00Z",
        )
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=BUCKET, Key=key, Body=content.encode("utf-8")
        )
        event = {"Records": [{"s3": {"object": {"key": key}}}]}
        return import_id, event

    def run(self, sub, content, **kw):
        import_id, event = self.start_import(sub, content, **kw)
        self.importer.handler(event, None)
        return self.dynamo.get_import(sub, import_id)


def test_import_lands_transactions_with_report(env):
    view = env.run("sub-1", FILE_A)
    assert view["status"] == "complete"
    assert view["added"] == 5
    assert view["duplicate"] == 0
    assert view["failed"] == 0
    txns = env.dynamo.query_transactions("sub-1", date_from="2026-07-01", date_to="2026-07-31")
    assert len(txns) == 5
    assert all(t["categoryStatus"] == "uncategorized" for t in txns)


def test_reuploading_same_file_adds_zero_duplicates(env):
    env.run("sub-1", FILE_A)
    # A brand-new import of the *identical* file → whole-file dedupe (FILEHASH#).
    view = env.run("sub-1", FILE_A)
    assert view["status"] == "duplicate"
    assert view["added"] == 0
    txns = env.dynamo.query_transactions("sub-1", date_from="2026-07-01", date_to="2026-07-31")
    assert len(txns) == 5  # still five, not ten


def test_overlapping_exports_dedupe(env):
    env.run("sub-1", FILE_A)          # 5 txns for 07/01–07/05
    view = env.run("sub-1", FILE_B)   # overlaps 07/03–07/05, adds 07/06
    assert view["status"] == "complete"
    assert view["added"] == 1         # only NEW F (07/06)
    assert view["duplicate"] == 3     # BOOK C / GAS D / FOOD E already present
    txns = env.dynamo.query_transactions("sub-1", date_from="2026-07-01", date_to="2026-07-31")
    assert len(txns) == 6             # 5 + 1


def test_identical_charges_all_kept_and_malformed_counted(env):
    view = env.run("sub-1", FILE_MIXED)
    assert view["added"] == 3         # three distinct MIRRA charges retained (ADR-012)
    assert view["failed"] == 1        # the broken date row counted, not fatal
    assert view["status"] == "complete"
    assert len(view["errors"]) == 1


def test_crash_replay_is_harmless(env):
    """Same importId re-delivered (crash/redelivery) resumes; no double counting."""
    import_id, event = env.start_import("sub-1", FILE_A)
    env.importer.handler(event, None)
    env.importer.handler(event, None)  # redelivery of the same S3 event
    view = env.dynamo.get_import("sub-1", import_id)
    assert view["added"] == 5         # not 10
    txns = env.dynamo.query_transactions("sub-1", date_from="2026-07-01", date_to="2026-07-31")
    assert len(txns) == 5


def test_distinct_users_are_isolated(env):
    env.run("sub-a", FILE_A)
    env.run("sub-b", FILE_A)  # same file, different user → not a duplicate for them
    a = env.dynamo.query_transactions("sub-a", date_from="2026-07-01", date_to="2026-07-31")
    b = env.dynamo.query_transactions("sub-b", date_from="2026-07-01", date_to="2026-07-31")
    assert len(a) == 5 and len(b) == 5


def test_import_enqueues_added_txns_for_categorization(env):
    """The import→categorize seam (Slice 5): only the *added* rows are enqueued, as locate keys."""
    _id, event = env.start_import("sub-1", FILE_A)
    env.importer.handler(event, None)

    messages = env.drain_queue()
    keyed = [k for m in messages for k in m["txnKeys"]]
    assert all(m["sub"] == "sub-1" for m in messages)
    assert len(keyed) == 5                         # the 5 added rows
    assert all(set(k) == {"date", "txnId"} for k in keyed)  # keys, not payloads


def test_duplicate_file_enqueues_nothing(env):
    env.run("sub-1", FILE_A)
    env.drain_queue()                              # clear the first import's messages
    env.run("sub-1", FILE_A)                       # whole-file duplicate → 0 added
    assert env.drain_queue() == []
