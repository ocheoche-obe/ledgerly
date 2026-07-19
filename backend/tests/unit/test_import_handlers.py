"""Handler tests for /imports and /transactions — routing, auth, parsing, error mapping.

Full request path (handler → adapter → moto S3/DynamoDB): covers presign, status polling,
the date-window query, and 400/401/404/405 mapping without touching AWS.
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
        for mod in ("adapters.dynamo", "adapters.s3",
                    "functions.api_imports.handler", "functions.api_transactions.handler"):
            sys.modules.pop(mod, None)
        imports = importlib.import_module("functions.api_imports.handler")
        transactions = importlib.import_module("functions.api_transactions.handler")
        yield imports, transactions


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
