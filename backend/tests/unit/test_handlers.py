"""Handler tests for /settings and /categories — routing, auth, parsing, and error mapping.

These run the full request path (handler → adapter → moto DynamoDB), so they cover the thin
handler logic (method routing, JWT-sub extraction, body parsing, 400/401/404/405) on top of
real boto3 calls, without touching AWS.
"""
from __future__ import annotations

import importlib
import json
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"


@pytest.fixture
def handlers(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
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
        for mod in ("adapters.dynamo", "functions.api_settings.handler",
                    "functions.api_categories.handler"):
            sys.modules.pop(mod, None)
        settings = importlib.import_module("functions.api_settings.handler")
        categories = importlib.import_module("functions.api_categories.handler")
        yield settings, categories


def _event(method, *, sub="s1", body=None, path_params=None):
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
    return event


def _body(res):
    return json.loads(res["body"])


# --- /settings -------------------------------------------------------------------------

def test_get_settings_returns_profile_and_current_cycle(handlers):
    settings, _ = handlers
    res = settings.handler(_event("GET"), None)
    assert res["statusCode"] == 200
    body = _body(res)
    assert body["cadences"][0]["kind"] == "monthly"
    # The engine-derived current cycle is surfaced live.
    assert body["currentCycle"]["cycleId"].startswith("M#")
    assert "start" in body["currentCycle"] and "end" in body["currentCycle"]


def test_get_settings_without_sub_is_401(handlers):
    settings, _ = handlers
    res = settings.handler(_event("GET", sub=None), None)
    assert res["statusCode"] == 401


def test_patch_settings_to_biweekly(handlers):
    settings, _ = handlers
    settings.handler(_event("GET"), None)  # ensure profile
    res = settings.handler(
        _event("PATCH", body={"cadence": {"kind": "biweekly", "anchor": "2099-01-08"}}), None
    )
    assert res["statusCode"] == 200
    assert _body(res)["cadences"][-1]["kind"] == "biweekly"


def test_patch_settings_rejects_bad_kind(handlers):
    settings, _ = handlers
    res = settings.handler(_event("PATCH", body={"cadence": {"kind": "weekly"}}), None)
    assert res["statusCode"] == 400


def test_patch_settings_biweekly_without_anchor_is_400(handlers):
    settings, _ = handlers
    res = settings.handler(_event("PATCH", body={"cadence": {"kind": "biweekly"}}), None)
    assert res["statusCode"] == 400


def test_patch_settings_non_object_cadence_is_400(handlers):
    # Valid JSON but cadence is a string, not an object — must be a clean 400, not a 500.
    settings, _ = handlers
    res = settings.handler(_event("PATCH", body={"cadence": "monthly"}), None)
    assert res["statusCode"] == 400


def test_settings_rejects_unknown_method(handlers):
    settings, _ = handlers
    res = settings.handler(_event("DELETE"), None)
    assert res["statusCode"] == 405


# --- /categories -----------------------------------------------------------------------

def test_get_categories_seeds_starters(handlers):
    _, categories = handlers
    res = categories.handler(_event("GET"), None)
    assert res["statusCode"] == 200
    assert len(_body(res)["categories"]) > 0


def test_post_category(handlers):
    _, categories = handlers
    res = categories.handler(_event("POST", body={"name": "Coffee"}), None)
    assert res["statusCode"] == 201
    assert _body(res)["name"] == "Coffee"


def test_post_category_blank_name_is_400(handlers):
    _, categories = handlers
    res = categories.handler(_event("POST", body={"name": "   "}), None)
    assert res["statusCode"] == 400


def test_patch_category_rename(handlers):
    _, categories = handlers
    created = _body(categories.handler(_event("POST", body={"name": "Coffe"}), None))
    res = categories.handler(
        _event("PATCH", body={"name": "Coffee"}, path_params={"id": created["categoryId"]}),
        None,
    )
    assert res["statusCode"] == 200
    assert _body(res)["name"] == "Coffee"


def test_patch_missing_category_is_404(handlers):
    _, categories = handlers
    res = categories.handler(
        _event("PATCH", body={"name": "X"}, path_params={"id": "nope"}), None
    )
    assert res["statusCode"] == 404


def test_patch_without_path_id_is_400(handlers):
    _, categories = handlers
    res = categories.handler(_event("PATCH", body={"name": "X"}), None)
    assert res["statusCode"] == 400


def test_categories_without_sub_is_401(handlers):
    _, categories = handlers
    res = categories.handler(_event("GET", sub=None), None)
    assert res["statusCode"] == 401
