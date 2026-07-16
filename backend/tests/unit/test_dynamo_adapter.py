"""Adapter tests for backend/adapters/dynamo.py against a moto-mocked DynamoDB.

The adapter binds its boto3 table at import time from TABLE_NAME, so each test starts moto,
creates the table, then imports the module fresh inside the mock (via a fixture that reloads
it). This exercises the real boto3 calls — GetItem, conditional PutItem — without touching AWS.
"""
from __future__ import annotations

import importlib
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"


@pytest.fixture
def dynamo(monkeypatch):
    """Yield a freshly-imported adapter bound to a moto table with the app's key schema."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    # The Lambda runtime always sets AWS_REGION; the test env (and CI) doesn't, so the
    # adapter's region-less boto3 resource would raise NoRegionError. Pin a region + dummy
    # credentials (standard moto hygiene) so nothing can reach real AWS.
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
        # Import fresh so the module-level table binds to the mocked resource.
        sys.modules.pop("adapters.dynamo", None)
        module = importlib.import_module("adapters.dynamo")
        yield module


def test_first_read_creates_default_monthly_profile(dynamo):
    view = dynamo.get_or_create_settings("sub-123")

    assert view["type"] == "PROFILE"
    assert len(view["cadences"]) == 1
    assert view["cadences"][0]["kind"] == "monthly"
    # The owner-facing projection never leaks the DynamoDB key attributes.
    assert "pk" not in view and "sk" not in view


def test_read_is_idempotent_and_persists_one_item(dynamo):
    first = dynamo.get_or_create_settings("sub-123")
    second = dynamo.get_or_create_settings("sub-123")

    # Same profile returned; the effectiveFrom created on first read is stable on re-read.
    assert first == second

    raw = dynamo._table.get_item(Key={"pk": "USER#sub-123", "sk": "PROFILE"})["Item"]
    assert raw["type"] == "PROFILE"


def test_distinct_users_get_distinct_profiles(dynamo):
    dynamo.get_or_create_settings("sub-a")
    dynamo.get_or_create_settings("sub-b")

    scan = dynamo._table.scan()["Items"]
    pks = {item["pk"] for item in scan}
    assert pks == {"USER#sub-a", "USER#sub-b"}
