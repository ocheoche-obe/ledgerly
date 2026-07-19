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


# --- categories (FR-4.1 / FR-4.4) ------------------------------------------------------

def test_first_list_seeds_starter_categories(dynamo):
    from core.categories import STARTER_CATEGORIES

    cats = dynamo.list_categories("sub-1")
    assert [c["name"] for c in cats] == list(STARTER_CATEGORIES)
    assert all(c["status"] == "active" for c in cats)
    # sortOrder came back as a plain int (Decimal would break JSON serialization).
    assert all(isinstance(c["sortOrder"], int) for c in cats)


def test_starter_seed_is_idempotent(dynamo):
    first = dynamo.list_categories("sub-1")
    second = dynamo.list_categories("sub-1")
    assert first == second  # no duplicate seeding on a second load


def test_starters_not_reseeded_after_deletion(dynamo):
    dynamo.list_categories("sub-1")  # seeds
    # Simulate the owner archiving everything, then deleting one — the seed flag stays set.
    cats = dynamo.list_categories("sub-1")
    dynamo._table.delete_item(
        Key={"pk": "USER#sub-1", "sk": f"CAT#{cats[0]['categoryId']}"}
    )
    remaining = dynamo.list_categories("sub-1")
    assert len(remaining) == len(cats) - 1  # not re-seeded back to full


def test_create_category_appends_after_starters(dynamo):
    starters = dynamo.list_categories("sub-1")
    created = dynamo.create_category("sub-1", "  Coffee  ")

    assert created["name"] == "Coffee"  # normalized
    assert created["status"] == "active"
    assert created["sortOrder"] == len(starters)  # appended at the end


def test_create_category_rejects_blank_name(dynamo):
    dynamo.list_categories("sub-1")
    with pytest.raises(ValueError, match="must not be empty"):
        dynamo.create_category("sub-1", "   ")


def test_rename_and_archive_category(dynamo):
    created = dynamo.create_category("sub-1", "Coffe")
    cid = created["categoryId"]

    renamed = dynamo.update_category("sub-1", cid, name="Coffee")
    assert renamed["name"] == "Coffee"

    archived = dynamo.update_category("sub-1", cid, status="archived")
    assert archived["status"] == "archived"
    assert archived["name"] == "Coffee"  # rename persisted


def test_update_missing_category_returns_none(dynamo):
    assert dynamo.update_category("sub-1", "does-not-exist", name="X") is None


def test_update_rejects_bad_status(dynamo):
    created = dynamo.create_category("sub-1", "Coffee")
    with pytest.raises(ValueError, match="status must be"):
        dynamo.update_category("sub-1", created["categoryId"], status="deleted")


# --- cadence change (FR-4.2) -----------------------------------------------------------

def test_update_cadence_to_biweekly_appends_history(dynamo):
    dynamo.get_or_create_settings("sub-1")  # default monthly
    view = dynamo.update_cadence("sub-1", kind="biweekly", anchor="2099-01-08")

    assert len(view["cadences"]) == 2
    latest = view["cadences"][-1]
    assert latest["kind"] == "biweekly"
    assert latest["anchor"] == "2099-01-08"
    # Persisted, not just returned.
    raw = dynamo._table.get_item(Key={"pk": "USER#sub-1", "sk": "PROFILE"})["Item"]
    assert len(raw["cadences"]) == 2


def test_update_cadence_creates_profile_if_missing(dynamo):
    # No prior GET /settings — update should still work by creating the PROFILE first.
    view = dynamo.update_cadence("sub-1", kind="biweekly", anchor="2099-01-08")
    assert view["cadences"][-1]["kind"] == "biweekly"
