"""Handler tests for /imports and /transactions — routing, auth, parsing, error mapping.

Full request path (handler → adapter → moto S3/DynamoDB/SQS): covers presign, status polling,
the date-window query, the [B-7] recategorize re-drive, and 400/401/404/405 mapping without
touching AWS.
"""
from __future__ import annotations

import importlib
import json
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"
BUCKET = "ledgerly-uploads-test"
QUEUE_NAME = "ledgerly-test-categorize"


@pytest.fixture
def handlers(monkeypatch):
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
        sqs = boto3.client("sqs", region_name="us-east-1")
        monkeypatch.setenv(
            "CATEGORIZE_QUEUE_URL", sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
        )
        for mod in ("adapters.dynamo", "adapters.s3", "adapters.sqs",
                    "functions.api_imports.handler", "functions.api_transactions.handler"):
            sys.modules.pop(mod, None)
        imports = importlib.import_module("functions.api_imports.handler")
        transactions = importlib.import_module("functions.api_transactions.handler")
        yield imports, transactions


def _seed_txn(txn_id, *, date, sub="s1", status="uncategorized"):
    """Put a transaction straight into the table (the importer's write path is tested
    elsewhere; here we only need rows for the window query to find)."""
    dynamo = importlib.import_module("adapters.dynamo")
    dynamo._table.put_item(Item={
        "pk": f"USER#{sub}", "sk": f"TXN#{date}#{txn_id}", "type": "TXN",
        "txnId": txn_id, "date": date, "amountCents": -1234, "direction": "debit",
        "balanceCents": 100000, "accountId": "chase-5980", "descriptionRaw": "SAFEWAY",
        "merchantNormalized": "safeway", "categoryId": None, "categoryStatus": status,
        "needsReview": False, "importId": "01IMP",
    })


def _queued_messages():
    """Every message currently on the categorization queue, as parsed bodies."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
    received = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
    return [json.loads(m["Body"]) for m in received]


def _event(method, *, sub="s1", body=None, path_params=None, query=None):
    event = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": sub}}} if sub else {},
        }
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if path_params is not None:
        event["pathParameters"] = path_params
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _body(res):
    return json.loads(res["body"])


# --- POST /imports (presign) -----------------------------------------------------------

def test_post_imports_returns_presigned_url_and_pending_record(handlers):
    imports, _ = handlers
    res = imports.handler(
        _event("POST", body={"filename": "Chase5980.csv", "accountLabel": "Chase ...5980"}), None
    )
    assert res["statusCode"] == 201
    body = _body(res)
    assert body["importId"]
    assert body["uploadUrl"].startswith("https://")
    assert body["status"] == "pending"
    assert body["accountLabel"] == "Chase ...5980"


def test_post_imports_requires_filename(handlers):
    imports, _ = handlers
    res = imports.handler(_event("POST", body={"accountLabel": "Chase"}), None)
    assert res["statusCode"] == 400


def test_post_imports_requires_account_label(handlers):
    imports, _ = handlers
    res = imports.handler(_event("POST", body={"filename": "f.csv"}), None)
    assert res["statusCode"] == 400


def test_post_imports_without_sub_is_401(handlers):
    imports, _ = handlers
    res = imports.handler(_event("POST", sub=None, body={"filename": "f.csv"}), None)
    assert res["statusCode"] == 401


# --- GET /imports + /imports/{id} ------------------------------------------------------

def test_get_import_by_id_and_list(handlers):
    imports, _ = handlers
    created = _body(imports.handler(
        _event("POST", body={"filename": "f.csv", "accountLabel": "Chase"}), None
    ))
    one = imports.handler(_event("GET", path_params={"id": created["importId"]}), None)
    assert one["statusCode"] == 200
    assert _body(one)["importId"] == created["importId"]

    listed = imports.handler(_event("GET"), None)
    assert listed["statusCode"] == 200
    assert len(_body(listed)["imports"]) == 1


def test_get_missing_import_is_404(handlers):
    imports, _ = handlers
    res = imports.handler(_event("GET", path_params={"id": "01JDOESNOTEXIST"}), None)
    assert res["statusCode"] == 404


# --- GET /transactions -----------------------------------------------------------------

def test_get_transactions_empty_ok(handlers):
    _, transactions = handlers
    res = transactions.handler(
        _event("GET", query={"from": "2026-07-01", "to": "2026-07-31"}), None
    )
    assert res["statusCode"] == 200
    assert _body(res)["transactions"] == []


def test_get_transactions_defaults_window_when_absent(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("GET"), None)
    assert res["statusCode"] == 200
    body = _body(res)
    assert "from" in body and "to" in body


def test_get_transactions_rejects_bad_date(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("GET", query={"from": "07-01-2026"}), None)
    assert res["statusCode"] == 400


def test_get_transactions_rejects_reversed_window(handlers):
    _, transactions = handlers
    res = transactions.handler(
        _event("GET", query={"from": "2026-07-31", "to": "2026-07-01"}), None
    )
    assert res["statusCode"] == 400


def test_get_transactions_without_sub_is_401(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("GET", sub=None), None)
    assert res["statusCode"] == 401


# --- POST /transactions/recategorize ([B-7]) -------------------------------------------

def test_recategorize_enqueues_uncategorized_rows_only(handlers):
    _, transactions = handlers
    _seed_txn("a1", date="2026-07-02")
    _seed_txn("a2", date="2026-07-03")
    _seed_txn("a3", date="2026-07-04", status="auto")  # already filed → left alone

    res = transactions.handler(
        _event("POST", body={"from": "2026-07-01", "to": "2026-07-31"}), None
    )

    assert res["statusCode"] == 202
    body = _body(res)
    assert body["scanned"] == 3
    assert body["enqueued"] == 2
    assert body["messages"] == 1
    assert "truncated" not in body

    (message,) = _queued_messages()
    assert {k["txnId"] for k in message["txnKeys"]} == {"a1", "a2"}
    assert "force" not in message  # default scope needs no force flag


def test_recategorize_include_categorized_widens_scope_and_sets_force(handlers):
    _, transactions = handlers
    _seed_txn("b1", date="2026-07-02")
    _seed_txn("b2", date="2026-07-03", status="auto")
    _seed_txn("b3", date="2026-07-04", status="corrected")  # owner decision — never re-run

    res = transactions.handler(
        _event("POST", body={"from": "2026-07-01", "to": "2026-07-31",
                             "includeCategorized": True}), None
    )

    assert res["statusCode"] == 202
    assert _body(res)["enqueued"] == 2
    (message,) = _queued_messages()
    assert {k["txnId"] for k in message["txnKeys"]} == {"b1", "b2"}
    assert message["force"] is True


def test_recategorize_with_nothing_to_do_enqueues_nothing(handlers):
    _, transactions = handlers
    _seed_txn("c1", date="2026-07-02", status="confirmed")

    res = transactions.handler(
        _event("POST", body={"from": "2026-07-01", "to": "2026-07-31"}), None
    )

    assert _body(res)["enqueued"] == 0
    assert _body(res)["messages"] == 0
    assert _queued_messages() == []


def test_recategorize_reports_a_truncated_window(handlers, monkeypatch):
    # The window query is single-page ([B-2]). A bulk backfill that quietly stops at the cap
    # would leave rows stranded — exactly the bug [B-7] exists to fix — so it must say so.
    _, transactions = handlers
    _seed_txn("d1", date="2026-07-02")
    _seed_txn("d2", date="2026-07-03")
    monkeypatch.setattr(transactions, "TXN_QUERY_LIMIT", 2)

    res = transactions.handler(
        _event("POST", body={"from": "2026-07-01", "to": "2026-07-31"}), None
    )

    body = _body(res)
    assert body["truncated"] is True
    assert "narrower windows" in body["message"]


def test_recategorize_rejects_bad_window(handlers):
    _, transactions = handlers
    res = transactions.handler(
        _event("POST", body={"from": "2026-07-31", "to": "2026-07-01"}), None
    )
    assert res["statusCode"] == 400


def test_recategorize_rejects_non_boolean_include_flag(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("POST", body={"includeCategorized": "yes"}), None)
    assert res["statusCode"] == 400


def test_recategorize_without_sub_is_401(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("POST", sub=None, body={}), None)
    assert res["statusCode"] == 401


def test_transactions_rejects_unsupported_method(handlers):
    _, transactions = handlers
    res = transactions.handler(_event("DELETE"), None)
    assert res["statusCode"] == 405
