"""Handler tests for /cycles — the dashboard read and the budget write (FR-4.3, FR-5.1–5.3).

Full request path (handler → adapter → moto DynamoDB), so the pieces the pure tests can't
cover are proven here: cycle resolution from a URL-safe reference, the cycle-major budget
query actually selecting one cycle's budgets, and budgets surviving a round trip.
"""
from __future__ import annotations

import importlib
import json
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"
SUB = "s1"


@pytest.fixture
def cycles(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for mod in ("adapters.dynamo", "functions.api_cycles.handler"):
            sys.modules.pop(mod, None)
        handler = importlib.import_module("functions.api_cycles.handler")
        yield handler


def _event(method, *, sub=SUB, path_params=None, body=None):
    event = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": sub}}} if sub else {},
        }
    }
    if path_params is not None:
        event["pathParameters"] = path_params
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(res):
    return json.loads(res["body"])


def _categories(handler):
    """The starter set, seeded on first read (FR-4.4) — gives us real category ids."""
    dynamo = importlib.import_module("adapters.dynamo")
    return dynamo.list_categories(SUB)


def _seed_txn(txn_id, *, date, amount_cents, category_id=None):
    dynamo = importlib.import_module("adapters.dynamo")
    dynamo._table.put_item(Item={
        "pk": f"USER#{SUB}", "sk": f"TXN#{date}#{txn_id}", "type": "TXN",
        "txnId": txn_id, "date": date, "amountCents": amount_cents,
        "direction": "credit" if amount_cents >= 0 else "debit",
        "balanceCents": 100000, "accountId": "chase-5980", "descriptionRaw": "X",
        "merchantNormalized": "x", "categoryId": category_id,
        "categoryStatus": "auto" if category_id else "uncategorized",
        "needsReview": False, "importId": "01IMP",
    })


# --- GET /cycles (the picker, AP 15) ----------------------------------------------------

def test_list_cycles_with_no_data_is_just_the_current_cycle(cycles):
    res = cycles.handler(_event("GET"), None)
    assert res["statusCode"] == 200
    body = _body(res)
    assert len(body["cycles"]) == 1
    assert body["cycles"][0]["cycleId"] == body["currentCycleId"]


def test_list_cycles_reaches_back_to_the_first_transaction(cycles):
    _seed_txn("old", date="2026-06-15", amount_cents=-500)
    res = cycles.handler(_event("GET"), None)
    ids = [c["cycleId"] for c in _body(res)["cycles"]]
    assert "M#2026-06" in ids
    assert ids[0] == _body(res)["currentCycleId"]  # newest first


# --- PUT budgets (AP 5, FR-4.3) ---------------------------------------------------------

def test_set_and_read_back_a_budget(cycles):
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    res = cycles.handler(
        _event("PUT", path_params={"cycleRef": "2026-07-15", "categoryId": groceries["categoryId"]},
               body={"amountCents": 40000}),
        None,
    )
    assert res["statusCode"] == 200
    assert _body(res)["cycle"]["cycleId"] == "M#2026-07"
    assert _body(res)["budget"]["amountCents"] == 40000

    summary = _body(cycles.handler(
        _event("GET", path_params={"cycleRef": "2026-07-02"}), None
    ))
    row = next(r for r in summary["perCategory"] if r["categoryId"] == groceries["categoryId"])
    assert row["budgetCents"] == 40000  # any date inside the cycle resolves to the same budget


def test_budgets_are_per_cycle(cycles):
    # FR-4.3: amounts can differ from cycle to cycle. The cycle is part of the key, so July's
    # budget must not leak into August's summary.
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    cat = groceries["categoryId"]
    cycles.handler(_event("PUT", path_params={"cycleRef": "2026-07-15", "categoryId": cat},
                          body={"amountCents": 40000}), None)
    cycles.handler(_event("PUT", path_params={"cycleRef": "2026-08-15", "categoryId": cat},
                          body={"amountCents": 55000}), None)

    july = _body(cycles.handler(_event("GET", path_params={"cycleRef": "2026-07-20"}), None))
    august = _body(cycles.handler(_event("GET", path_params={"cycleRef": "2026-08-20"}), None))
    assert next(r for r in july["perCategory"] if r["categoryId"] == cat)["budgetCents"] == 40000
    assert next(r for r in august["perCategory"] if r["categoryId"] == cat)["budgetCents"] == 55000


def test_clearing_a_budget_removes_the_target(cycles):
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    cat = groceries["categoryId"]
    cycles.handler(_event("PUT", path_params={"cycleRef": "2026-07-15", "categoryId": cat},
                          body={"amountCents": 40000}), None)
    res = cycles.handler(_event("PUT", path_params={"cycleRef": "2026-07-15", "categoryId": cat},
                                body={"amountCents": None}), None)
    assert _body(res)["budget"] is None

    summary = _body(cycles.handler(_event("GET", path_params={"cycleRef": "2026-07-15"}), None))
    row = next(r for r in summary["perCategory"] if r["categoryId"] == cat)
    assert row["budgetCents"] is None  # absent, not zero


def test_budget_for_unknown_category_is_rejected(cycles):
    _categories(cycles)  # seed the starter set so the check has something to compare against
    res = cycles.handler(
        _event("PUT", path_params={"cycleRef": "current", "categoryId": "01NOPE"},
               body={"amountCents": 100}),
        None,
    )
    assert res["statusCode"] == 400
    assert "unknown categoryId" in _body(res)["message"]


def test_budget_rejects_a_negative_amount(cycles):
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    res = cycles.handler(
        _event("PUT", path_params={"cycleRef": "current", "categoryId": groceries["categoryId"]},
               body={"amountCents": -1}),
        None,
    )
    assert res["statusCode"] == 400


def test_budget_requires_the_amount_field(cycles):
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    res = cycles.handler(
        _event("PUT", path_params={"cycleRef": "current", "categoryId": groceries["categoryId"]},
               body={}),
        None,
    )
    assert res["statusCode"] == 400


# --- GET summary (AP 4+6, architecture §3.3) --------------------------------------------

def test_summary_aggregates_the_cycle_window_only(cycles):
    groceries = next(c for c in _categories(cycles) if c["name"] == "Groceries")
    cat = groceries["categoryId"]
    _seed_txn("in", date="2026-07-10", amount_cents=-5000, category_id=cat)
    _seed_txn("edge_start", date="2026-07-01", amount_cents=-1000, category_id=cat)
    _seed_txn("edge_end", date="2026-07-31", amount_cents=-2000, category_id=cat)
    _seed_txn("out", date="2026-08-01", amount_cents=-9999, category_id=cat)  # next cycle

    summary = _body(cycles.handler(_event("GET", path_params={"cycleRef": "2026-07-15"}), None))

    assert summary["cycle"]["start"] == "2026-07-01"
    assert summary["cycle"]["end"] == "2026-07-31"
    row = next(r for r in summary["perCategory"] if r["categoryId"] == cat)
    assert row["spentCents"] == 8000  # the boundary days are included, August is not
    assert summary["totals"]["transactionCount"] == 3


def test_summary_accepts_current_as_the_reference(cycles):
    res = cycles.handler(_event("GET", path_params={"cycleRef": "current"}), None)
    assert res["statusCode"] == 200
    assert _body(res)["cycle"]["cycleId"].startswith(("M#", "B#"))


def test_summary_rejects_a_malformed_cycle_reference(cycles):
    res = cycles.handler(_event("GET", path_params={"cycleRef": "M#2026-07"}), None)
    assert res["statusCode"] == 400
    assert "ISO date" in _body(res)["message"]


def test_summary_reports_uncategorized_money(cycles):
    _categories(cycles)
    _seed_txn("u1", date="2026-07-10", amount_cents=-4200)
    summary = _body(cycles.handler(_event("GET", path_params={"cycleRef": "2026-07-10"}), None))
    assert summary["totals"]["uncategorizedCount"] == 1
    assert summary["perCategory"][-1]["spentCents"] == 4200


# --- auth & method mapping --------------------------------------------------------------

def test_without_sub_is_401(cycles):
    assert cycles.handler(_event("GET", sub=None), None)["statusCode"] == 401


def test_unsupported_method_is_405(cycles):
    res = cycles.handler(_event("DELETE", path_params={"cycleRef": "current"}), None)
    assert res["statusCode"] == 405
