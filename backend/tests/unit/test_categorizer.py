"""Integration tests for the categorizer Lambda (functions/categorizer) against moto DynamoDB.

Drives the real pipeline — SQS message → read txns → rule/LLM decision → conditional update +
GSI maintenance — with a *fake* Categorizer injected in place of Bedrock (no live model, no
AWS Bedrock). This is where the decision matrix, idempotency, correction-preserving guard, and
partial-batch-failure behavior are proven end-to-end.
"""
from __future__ import annotations

import importlib
import json
import sys

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "ledgerly-test"
SUB = "sub-1"
CAT_FOOD = "01CATFOOD"
CAT_RENT = "01CATRENT"


class FakeCategorizer:
    """Stand-in for BedrockCategorizer. Returns canned {categoryId, confidence} per txnId and
    counts calls so idempotency (no redundant LLM call on replay) is observable."""

    def __init__(self, mapping: dict[str, tuple[str | None, float]]):
        self.mapping = mapping
        self.calls = 0
        self.raise_for: str | None = None

    def categorize(self, transactions, *, categories, corrections):
        self.calls += 1
        if self.raise_for and any(t["txnId"] == self.raise_for for t in transactions):
            raise RuntimeError("bedrock unavailable")
        out = []
        for t in transactions:
            cat, conf = self.mapping.get(t["txnId"], (None, 0.0))
            out.append({"txnId": t["txnId"], "categoryId": cat, "confidence": conf})
        return out


@pytest.fixture
def cat(monkeypatch):
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
        for mod in ("adapters.dynamo", "adapters.bedrock", "functions.categorizer.handler"):
            sys.modules.pop(mod, None)
        dynamo = importlib.import_module("adapters.dynamo")
        handler = importlib.import_module("functions.categorizer.handler")
        yield _Env(dynamo, handler)


class _Env:
    def __init__(self, dynamo, handler):
        self.dynamo = dynamo
        self.handler = handler
        # Seed the owner's two active categories.
        for cid, name, order in [(CAT_FOOD, "Groceries", 0), (CAT_RENT, "Housing", 1)]:
            self.dynamo._table.put_item(Item={
                "pk": f"USER#{SUB}", "sk": f"CAT#{cid}", "type": "CAT",
                "categoryId": cid, "name": name, "status": "active", "sortOrder": order,
            })

    def seed_txn(self, txn_id, *, date, merchant, status="uncategorized"):
        item = {
            "type": "TXN", "txnId": txn_id, "date": date, "amountCents": -1000,
            "direction": "debit", "balanceCents": 5000, "accountId": "chase-5980",
            "descriptionRaw": merchant.upper(), "merchantNormalized": merchant,
            "categoryId": None, "categoryStatus": status, "needsReview": False,
            "importId": "01IMP",
        }
        self.dynamo._table.put_item(Item={
            "pk": f"USER#{SUB}", "sk": f"TXN#{date}#{txn_id}", **item,
        })

    def seed_rule(self, merchant, category_id):
        self.dynamo._table.put_item(Item={
            "pk": f"USER#{SUB}", "sk": f"RULE#{merchant}", "type": "RULE",
            "merchantNormalized": merchant, "categoryId": category_id,
            "source": "correction", "hitCount": 1, "updatedAt": "2026-07-21T00:00:00Z",
        })

    def inject(self, categorizer):
        self.handler._categorizer = categorizer

    def run(self, txn_keys, *, message_id="m1"):
        event = {"Records": [{"messageId": message_id,
                              "body": json.dumps({"sub": SUB, "txnKeys": txn_keys})}]}
        return self.handler.handler(event, None)

    def raw(self, txn_id, date):
        return self.dynamo._table.get_item(
            Key={"pk": f"USER#{SUB}", "sk": f"TXN#{date}#{txn_id}"}).get("Item")


def test_llm_high_confidence_categorizes_auto_with_gsi1(cat):
    cat.seed_txn("t1", date="2026-07-03", merchant="trader joes")
    cat.inject(FakeCategorizer({"t1": (CAT_FOOD, 0.95)}))

    out = cat.run([{"date": "2026-07-03", "txnId": "t1"}])

    assert out == {"batchItemFailures": []}
    item = cat.raw("t1", "2026-07-03")
    assert item["categoryId"] == CAT_FOOD
    assert item["categoryStatus"] == "auto"
    assert item["needsReview"] is False
    assert item["gsi1pk"] == f"USER#{SUB}#CAT#{CAT_FOOD}"
    assert "gsi2pk" not in item  # not in the review queue


def test_llm_low_confidence_keeps_guess_and_enters_review_queue(cat):
    cat.seed_txn("t2", date="2026-07-04", merchant="mystery merch")
    cat.inject(FakeCategorizer({"t2": (CAT_RENT, 0.3)}))

    cat.run([{"date": "2026-07-04", "txnId": "t2"}])

    item = cat.raw("t2", "2026-07-04")
    assert item["categoryId"] == CAT_RENT
    assert item["categoryStatus"] == "auto"
    assert item["needsReview"] is True
    assert item["gsi1pk"] == f"USER#{SUB}#CAT#{CAT_RENT}"      # counts as a best guess
    assert item["gsi2pk"] == f"USER#{SUB}#REVIEW"              # and flagged for review


def test_llm_null_category_stays_uncategorized_and_flagged(cat):
    cat.seed_txn("t3", date="2026-07-05", merchant="???")
    cat.inject(FakeCategorizer({"t3": (None, 0.9)}))

    cat.run([{"date": "2026-07-05", "txnId": "t3"}])

    item = cat.raw("t3", "2026-07-05")
    assert item["categoryId"] is None
    assert item["categoryStatus"] == "uncategorized"
    assert item["needsReview"] is True
    assert "gsi1pk" not in item                                # no category → not on GSI1
    assert item["gsi2pk"] == f"USER#{SUB}#REVIEW"


def test_llm_unknown_category_id_is_treated_as_uncategorized(cat):
    cat.seed_txn("t4", date="2026-07-06", merchant="weird")
    cat.inject(FakeCategorizer({"t4": ("01NOTAREALCAT", 0.99)}))

    cat.run([{"date": "2026-07-06", "txnId": "t4"}])

    item = cat.raw("t4", "2026-07-06")
    assert item["categoryId"] is None
    assert item["categoryStatus"] == "uncategorized"


def test_merchant_rule_hit_skips_the_llm(cat):
    cat.seed_rule("blue bottle cof", CAT_FOOD)
    cat.seed_txn("t5", date="2026-07-07", merchant="blue bottle cof")
    fake = FakeCategorizer({})  # would return nothing; a rule hit must not call it
    cat.inject(fake)

    cat.run([{"date": "2026-07-07", "txnId": "t5"}])

    item = cat.raw("t5", "2026-07-07")
    assert item["categoryId"] == CAT_FOOD
    assert item["categoryStatus"] == "auto"
    assert float(item["confidence"]) == 1.0
    assert fake.calls == 0  # LLM skipped entirely


def test_replay_of_categorized_batch_is_a_noop(cat):
    cat.seed_txn("t6", date="2026-07-08", merchant="trader joes")
    fake = FakeCategorizer({"t6": (CAT_FOOD, 0.95)})
    cat.inject(fake)
    keys = [{"date": "2026-07-08", "txnId": "t6"}]

    cat.run(keys)
    cat.run(keys)  # SQS at-least-once redelivery

    # Second run finds the txn already 'auto' → skips it, so no second LLM call.
    assert fake.calls == 1


def test_owner_correction_is_never_overwritten(cat):
    # An already-corrected txn that somehow gets re-enqueued must keep the owner's choice.
    cat.seed_txn("t7", date="2026-07-09", merchant="trader joes", status="corrected")
    cat.dynamo._table.update_item(
        Key={"pk": f"USER#{SUB}", "sk": "TXN#2026-07-09#t7"},
        UpdateExpression="SET categoryId = :c", ExpressionAttributeValues={":c": CAT_RENT},
    )
    cat.inject(FakeCategorizer({"t7": (CAT_FOOD, 0.99)}))

    cat.run([{"date": "2026-07-09", "txnId": "t7"}])

    item = cat.raw("t7", "2026-07-09")
    assert item["categoryStatus"] == "corrected"  # untouched
    assert item["categoryId"] == CAT_RENT         # owner's category preserved


def test_archived_categories_are_not_offered_to_the_model(cat):
    # Retiring a category must remove it from the categorizer's target set (the model must not
    # assign a txn to a bucket the owner archived).
    cat.dynamo._table.update_item(
        Key={"pk": f"USER#{SUB}", "sk": f"CAT#{CAT_RENT}"},
        UpdateExpression="SET #s = :a", ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":a": "archived"},
    )
    choices = cat.dynamo.list_category_choices(SUB)
    ids = {c["categoryId"] for c in choices}
    assert ids == {CAT_FOOD}


def test_model_failure_reports_partial_batch_failure_and_leaves_txn_uncategorized(cat):
    cat.seed_txn("t8", date="2026-07-10", merchant="boom")
    fake = FakeCategorizer({"t8": (CAT_FOOD, 0.9)})
    fake.raise_for = "t8"
    cat.inject(fake)

    out = cat.run([{"date": "2026-07-10", "txnId": "t8"}], message_id="m-boom")

    # The whole message is reported failed so SQS redelivers it (→ DLQ after 3) — FR-3.5.
    assert out == {"batchItemFailures": [{"itemIdentifier": "m-boom"}]}
    item = cat.raw("t8", "2026-07-10")
    assert item["categoryStatus"] == "uncategorized"  # nothing lost
