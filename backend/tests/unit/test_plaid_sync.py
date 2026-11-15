"""Integration tests for the Plaid Lambdas (ADR-014) against moto DynamoDB + SQS + Secrets
Manager, with a scripted fake standing in for Plaid.

These drive the real flow — exchange → Item record → sync worker → transaction items →
categorization queue — and pin the properties the owner is relying on: nothing is counted
twice, a category survives whatever Plaid does to a transaction, the cursor only moves after
the writes, and the access token appears nowhere it shouldn't.
"""
from __future__ import annotations

import importlib
import json
import logging
import sys

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from moto import mock_aws

from adapters.plaid import PlaidError
from core.categorize import Decision

TABLE_NAME = "ledgerly-test"
SUB = "user-123"
ITEM_ID = "item-abc"
ACCESS_TOKEN = "access-sandbox-SECRET-TOKEN-VALUE"
PUBLIC_TOKEN = "public-sandbox-ONE-TIME-VALUE"
KEYS_SECRET = "ledgerly/test/plaid/api-keys"
TOKENS_SECRET = "ledgerly/test/plaid/access-tokens"

ACCOUNT = {
    "account_id": "acc-1", "name": "Plaid Checking", "official_name": "Plaid Gold Checking",
    "mask": "0000", "type": "depository", "subtype": "checking",
    "balances": {"current": 110, "available": 100, "iso_currency_code": "USD"},
}


def txn(txn_id, *, amount=10.0, date="2026-11-10", pending=False, pending_id=None,
        merchant="Coffee Shop") -> dict:
    return {
        "transaction_id": txn_id, "account_id": "acc-1", "amount": amount, "date": date,
        "name": merchant.upper(), "merchant_name": merchant, "pending": pending,
        "pending_transaction_id": pending_id, "payment_channel": "in store",
        "iso_currency_code": "USD",
    }


def page(*, added=(), modified=(), removed=(), next_cursor, has_more=False) -> dict:
    return {"added": list(added), "modified": list(modified),
            "removed": [{"transaction_id": r, "account_id": "acc-1"} for r in removed],
            "next_cursor": next_cursor, "has_more": has_more, "request_id": f"req-{next_cursor}"}


def mutation_error() -> PlaidError:
    return PlaidError(error_type="TRANSACTIONS_ERROR",
                      error_code="TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION",
                      request_id="req-mut", status=400, endpoint="/transactions/sync")


class FakePlaid:
    """Scripted Plaid. ``script`` is a list of pages (or exceptions) served in order."""

    plaid_env = "sandbox"

    def __init__(self):
        self.script: list = []
        self.sync_cursors: list[str] = []
        self.exchanged: list[str] = []
        self.refreshed: list[str] = []

    def link_token_create(self, *, client_user_id):
        return {"link_token": "link-sandbox-123", "expiration": "2026-11-15T12:00:00Z",
                "request_id": "req-link"}

    def item_public_token_exchange(self, *, public_token):
        self.exchanged.append(public_token)
        return {"access_token": ACCESS_TOKEN, "item_id": ITEM_ID, "request_id": "req-exchange"}

    def accounts_get(self, *, access_token):
        assert access_token == ACCESS_TOKEN
        return {"accounts": [ACCOUNT],
                "item": {"item_id": ITEM_ID, "institution_id": "ins_109508",
                         "institution_name": "First Platypus Bank"}}

    def transactions_sync(self, *, access_token, cursor):
        assert access_token == ACCESS_TOKEN
        self.sync_cursors.append(cursor)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def sandbox_public_token_create(self, *, institution_id, username, password):
        return {"public_token": PUBLIC_TOKEN, "request_id": "req-sandbox"}

    def transactions_refresh(self, *, access_token):
        self.refreshed.append(access_token)
        return {"request_id": "req-refresh"}


class Env:
    def __init__(self, dynamo, api, worker, plaid, queue_url, started):
        self.dynamo, self.api, self.worker, self.plaid = dynamo, api, worker, plaid
        self.queue_url, self.started = queue_url, started
        self.table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)

    def api_call(self, path, body=None, *, sub=SUB):
        event = {"requestContext": {"http": {"method": "POST", "path": path}},
                 "body": json.dumps(body or {})}
        if sub:
            event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": sub}}}
        response = self.api.handler(event, None)
        return response["statusCode"], json.loads(response["body"]), response["body"]

    def link(self):
        status, body, _ = self.api_call("/plaid/exchange", {"publicToken": PUBLIC_TOKEN})
        assert status == 201
        return body

    def run_worker(self, *pages):
        """Start a sync through the API and run the worker on what it queued."""
        self.plaid.script = list(pages)
        status, body, _ = self.api_call("/plaid/sync")
        assert status == 202
        import_id = body["imports"][0]["importId"]
        result = self.worker.handler(self.started[-1], None)
        return result, self.dynamo.get_import(SUB, import_id)

    def all_items(self) -> list[dict]:
        return self.table.query(KeyConditionExpression=Key("pk").eq(f"USER#{SUB}"))["Items"]

    def txns(self) -> dict[str, dict]:
        return {i["txnId"]: i for i in self.all_items() if i["sk"].startswith("TXN#")}

    def pointers(self) -> set[str]:
        return {i["sk"].removeprefix("PLAIDTXN#") for i in self.all_items()
                if i["sk"].startswith("PLAIDTXN#")}

    def cursor(self) -> str:
        return self.dynamo.get_plaid_item(SUB, ITEM_ID)["cursor"]

    def drain_queue(self) -> list[str]:
        sqs = boto3.client("sqs", region_name="us-east-1")
        ids: list[str] = []
        while True:
            batch = sqs.receive_message(QueueUrl=self.queue_url,
                                        MaxNumberOfMessages=10).get("Messages", [])
            if not batch:
                return ids
            for message in batch:
                ids += [k["txnId"] for k in json.loads(message["Body"])["txnKeys"]]
                sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message["ReceiptHandle"])

    def categorize(self, txn_id, category_id="cat-food", *, status="corrected"):
        """Put a category on a stored row the way the categorizer / owner would."""
        row = self.txns()[txn_id]
        applied = self.dynamo.apply_categorization(
            SUB, row["date"], txn_id,
            Decision(category_id=category_id, status=status, confidence=0.95,
                     needs_review=False, source="llm"),
        )
        assert applied


@pytest.fixture
def env(monkeypatch):
    for name, value in (
        ("TABLE_NAME", TABLE_NAME), ("AWS_DEFAULT_REGION", "us-east-1"),
        ("AWS_ACCESS_KEY_ID", "testing"), ("AWS_SECRET_ACCESS_KEY", "testing"),
        ("AWS_SESSION_TOKEN", "testing"), ("PLAID_ENV", "sandbox"),
        ("PLAID_KEYS_SECRET_ID", KEYS_SECRET), ("PLAID_TOKENS_SECRET_ID", TOKENS_SECRET),
        ("PLAID_SYNC_FUNCTION_NAME", "ledgerly-test-plaid-sync"),
    ):
        monkeypatch.setenv(name, value)
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("secretsmanager", region_name="us-east-1").create_secret(
            Name=TOKENS_SECRET, SecretString='{"items":{}}')
        queue_url = boto3.client("sqs", region_name="us-east-1").create_queue(
            QueueName="ledgerly-categorize-test")["QueueUrl"]
        monkeypatch.setenv("CATEGORIZE_QUEUE_URL", queue_url)

        modules = ("adapters.dynamo", "adapters.sqs", "adapters.secrets",
                   "adapters.lambda_invoke", "functions.api_plaid.handler",
                   "functions.plaid_sync.handler", "functions.plaid_sync.on_failure")
        for mod in modules:
            sys.modules.pop(mod, None)
        dynamo = importlib.import_module("adapters.dynamo")
        api = importlib.import_module("functions.api_plaid.handler")
        worker = importlib.import_module("functions.plaid_sync.handler")
        monkeypatch.setattr(dynamo.time, "sleep", lambda _s: None)

        plaid = FakePlaid()
        api._plaid = plaid
        worker._plaid = plaid
        started: list[dict] = []
        monkeypatch.setattr(
            api, "start_plaid_sync",
            lambda *, sub, item_id, import_id: started.append(
                {"sub": sub, "itemId": item_id, "importId": import_id}),
        )
        yield Env(dynamo, api, worker, plaid, queue_url, started)


# --- link token + exchange ---------------------------------------------------------------


def test_requests_without_a_verified_identity_are_rejected(env):
    status, _, _ = env.api_call("/plaid/link-token", sub=None)
    assert status == 401


def test_link_token_is_returned_to_the_browser(env):
    status, body, _ = env.api_call("/plaid/link-token")
    assert status == 200
    assert body == {"linkToken": "link-sandbox-123", "expiration": "2026-11-15T12:00:00Z"}


def test_exchange_requires_a_public_token(env):
    status, body, _ = env.api_call("/plaid/exchange", {})
    assert status == 400
    assert "publicToken" in body["message"]


def test_exchange_stores_the_item_and_starts_the_first_sync(env):
    body = env.link()
    assert body["itemId"] == ITEM_ID
    assert body["institutionName"] == "First Platypus Bank"
    assert body["accounts"][0]["accountId"] == "plaid-checking-0000"
    assert body["accounts"][0]["balanceCurrentCents"] == 11000
    assert env.started == [{"sub": SUB, "itemId": ITEM_ID, "importId": body["importId"]}]
    record = env.dynamo.get_import(SUB, body["importId"])
    assert (record["source"], record["status"]) == ("plaid", "pending")


def test_the_access_token_is_only_ever_in_secrets_manager(env, caplog):
    caplog.set_level(logging.INFO)  # what the handlers run at; DEBUG would be botocore wire logs
    status, _, raw_response = env.api_call("/plaid/exchange", {"publicToken": PUBLIC_TOKEN})
    assert status == 201
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))

    assert ACCESS_TOKEN not in raw_response
    assert ACCESS_TOKEN not in json.dumps(env.all_items(), default=str)
    assert ACCESS_TOKEN not in json.dumps(env.started)
    assert ACCESS_TOKEN not in caplog.text
    assert PUBLIC_TOKEN not in caplog.text

    stored = boto3.client("secretsmanager", region_name="us-east-1").get_secret_value(
        SecretId=TOKENS_SECRET)["SecretString"]
    assert json.loads(stored)["items"][ITEM_ID] == {"sub": SUB, "accessToken": ACCESS_TOKEN}


def test_linking_the_same_bank_twice_is_refused_before_exchanging(env):
    env.link()
    status, body, _ = env.api_call("/plaid/exchange", {
        "publicToken": "public-sandbox-second", "institution": {"id": "ins_109508"}})
    assert status == 409
    assert body["itemId"] == ITEM_ID
    assert env.plaid.exchanged == [PUBLIC_TOKEN]  # the second token was never exchanged


def test_a_repeated_exchange_keeps_the_existing_item_and_its_cursor(env):
    env.link()
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    env.link()  # same public token again → same Item
    assert env.cursor() == "c1"


def test_plaid_errors_surface_as_502_with_the_code_and_request_id(env):
    def fail(*, client_user_id):
        raise PlaidError(error_type="INVALID_INPUT", error_code="INVALID_API_KEYS",
                         request_id="req-9", status=400, endpoint="/link/token/create")

    env.plaid.link_token_create = fail
    status, body, _ = env.api_call("/plaid/link-token")
    assert status == 502
    assert (body["errorCode"], body["requestId"]) == ("INVALID_API_KEYS", "req-9")


def test_sync_of_an_unknown_item_is_404(env):
    status, _, _ = env.api_call("/plaid/sync", {"itemId": "nope"})
    assert status == 404


# --- the sync worker -----------------------------------------------------------------------


def test_first_sync_adds_rows_flags_pending_and_enqueues_them(env):
    env.link()
    result, record = env.run_worker(
        page(added=[txn("t1"), txn("t2", amount=-500.0)], next_cursor="c1", has_more=True),
        page(added=[txn("p1", pending=True)], next_cursor="c2"),
    )
    assert env.plaid.sync_cursors == ["", "c1"]  # first call asks for full history
    assert result["added"] == 3
    assert result["pendingAdded"] == 1
    assert (record["status"], record["added"], record["done"]) == ("complete", 3, True)

    rows = env.txns()
    assert rows["t1"]["amountCents"] == -1000         # Plaid positive = money out
    assert rows["t2"]["amountCents"] == 50000
    assert rows["p1"]["pending"] is True
    assert rows["t1"]["categoryStatus"] == "uncategorized"
    assert rows["t1"]["accountId"] == "plaid-checking-0000"
    assert rows["t1"]["plaidEnv"] == "sandbox"
    assert env.pointers() == {"t1", "t2", "p1"}
    assert env.cursor() == "c2"
    assert sorted(env.drain_queue()) == ["p1", "t1", "t2"]


def test_a_second_sync_with_nothing_new_adds_zero(env):
    env.link()
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    env.drain_queue()
    result, record = env.run_worker(page(next_cursor="c1"))
    assert env.plaid.sync_cursors[-1] == "c1"  # resumed from the stored cursor
    assert (result["added"], result["modified"], result["removed"]) == (0, 0, 0)
    assert record["status"] == "complete"
    assert env.drain_queue() == []
    assert len(env.txns()) == 1


def test_mutation_during_pagination_restarts_and_applies_nothing_twice(env):
    env.link()
    result, _ = env.run_worker(
        page(added=[txn("stale")], next_cursor="c1", has_more=True),
        mutation_error(),
        page(added=[txn("t1")], next_cursor="c1b", has_more=True),
        page(added=[txn("t2")], next_cursor="c2"),
    )
    assert env.plaid.sync_cursors == ["", "c1", "", "c1b"]  # restarted from the start cursor
    assert set(env.txns()) == {"t1", "t2"}                  # the abandoned page left no trace
    assert result["added"] == 2
    assert env.cursor() == "c2"


def test_a_failed_sync_leaves_the_cursor_alone_and_reports_failure(env):
    env.link()
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    failure = PlaidError(error_type="ITEM_ERROR", error_code="ITEM_LOGIN_REQUIRED",
                         request_id="req-7", status=400, endpoint="/transactions/sync")
    result, record = env.run_worker(page(added=[txn("t2")], next_cursor="c2", has_more=True),
                                    failure)
    assert result["status"] == "failed"
    assert record["status"] == "failed"
    assert "ITEM_LOGIN_REQUIRED" in record["errors"][0]["error"]
    assert env.cursor() == "c1"
    assert set(env.txns()) == {"t1"}  # the buffered first page was never applied


def test_replaying_a_sync_whose_cursor_was_never_saved_converges(env):
    """Simulates a crash after the writes but before the cursor save."""
    env.link()
    pages = [page(added=[txn("t1"), txn("p1", pending=True)], next_cursor="c1")]
    env.run_worker(*pages)
    env.table.update_item(  # roll the cursor back, as if it had never been saved
        Key={"pk": f"USER#{SUB}", "sk": f"PLAIDITEM#{ITEM_ID}"},
        UpdateExpression="SET #c = :empty", ExpressionAttributeNames={"#c": "cursor"},
        ExpressionAttributeValues={":empty": ""})
    env.drain_queue()
    result, record = env.run_worker(*pages)
    assert result["added"] == 0
    assert record["duplicate"] == 2
    assert len(env.txns()) == 2
    assert env.drain_queue() == []
    assert env.cursor() == "c1"


def test_pending_then_posted_is_one_transaction_and_keeps_the_owners_category(env):
    env.link()
    env.run_worker(page(added=[txn("p1", pending=True, amount=20.0, date="2026-11-10")],
                        next_cursor="c1"))
    env.categorize("p1", "cat-dining", status="corrected")
    env.drain_queue()

    # The removal of the pending ID and the posted row arrive in *different pages*, removal
    # first, with a tip added and a later date.
    result, record = env.run_worker(
        page(removed=["p1"], next_cursor="c2", has_more=True),
        page(added=[txn("t9", pending_id="p1", amount=24.0, date="2026-11-12")],
             next_cursor="c3"),
    )
    rows = env.txns()
    assert set(rows) == {"t9"}                     # one row, not two
    posted = rows["t9"]
    assert posted["pending"] is False
    assert posted["amountCents"] == -2400
    assert posted["date"] == "2026-11-12"
    assert posted["categoryId"] == "cat-dining"    # the correction survived posting
    assert posted["categoryStatus"] == "corrected"
    assert posted["gsi1sk"] == "TXN#2026-11-12#t9"  # index keys rebuilt for the new row
    assert env.pointers() == {"t9"}
    assert (result["added"], result["merged"], result["removed"]) == (0, 1, 0)
    assert record["modified"] == 1
    assert record["duplicate"] == 0
    assert env.drain_queue() == []                 # nothing re-categorized


def test_a_posted_row_whose_pending_row_was_never_categorized_is_enqueued(env):
    env.link()
    env.run_worker(page(added=[txn("p1", pending=True)], next_cursor="c1"))
    env.drain_queue()
    env.run_worker(page(added=[txn("t9", pending_id="p1")], removed=["p1"], next_cursor="c2"))
    assert set(env.txns()) == {"t9"}
    assert env.drain_queue() == ["t9"]


def test_a_posted_row_whose_pending_row_is_already_gone_is_added_fresh(env):
    env.link()
    env.run_worker(page(added=[txn("p1", pending=True)], next_cursor="c1"))
    env.run_worker(page(removed=["p1"], next_cursor="c2"))  # removed in an earlier sync
    env.drain_queue()
    result, _ = env.run_worker(page(added=[txn("t9", pending_id="p1")], next_cursor="c3"))
    assert set(env.txns()) == {"t9"}
    assert result["added"] == 1
    assert env.drain_queue() == ["t9"]


def test_modified_updates_source_fields_and_preserves_the_category(env):
    env.link()
    env.run_worker(page(added=[txn("t1", amount=10.0, merchant="Coffee Shop")],
                        next_cursor="c1"))
    env.categorize("t1", "cat-food", status="corrected")
    env.drain_queue()
    result, record = env.run_worker(
        page(modified=[txn("t1", amount=12.5, merchant="Coffee Shop Downtown")],
             next_cursor="c2"))
    row = env.txns()["t1"]
    assert row["amountCents"] == -1250
    assert row["merchantNormalized"] == "coffee shop downtown"
    assert (row["categoryId"], row["categoryStatus"]) == ("cat-food", "corrected")
    assert row["gsi1pk"] == f"USER#{SUB}#CAT#cat-food"
    assert (result["modified"], record["modified"]) == (1, 1)
    assert env.drain_queue() == []


def test_modified_with_a_new_date_moves_the_row_and_carries_the_category(env):
    env.link()
    env.run_worker(page(added=[txn("t1", date="2026-11-10")], next_cursor="c1"))
    env.categorize("t1", "cat-food", status="auto")
    env.run_worker(page(modified=[txn("t1", date="2026-11-13")], next_cursor="c2"))
    rows = [i for i in env.all_items() if i["sk"].startswith("TXN#")]
    assert [r["sk"] for r in rows] == ["TXN#2026-11-13#t1"]  # moved, not duplicated
    assert rows[0]["categoryId"] == "cat-food"
    assert rows[0]["gsi1sk"] == "TXN#2026-11-13#t1"
    assert env.dynamo.get_plaid_txn_date(SUB, "t1") == "2026-11-13"


def test_modified_for_a_row_we_never_stored_is_added(env):
    env.link()
    result, _ = env.run_worker(page(modified=[txn("t1")], next_cursor="c1"))
    assert result["added"] == 1
    assert env.drain_queue() == ["t1"]


def test_removed_deletes_the_row_and_its_pointer(env):
    env.link()
    env.run_worker(page(added=[txn("t1"), txn("t2")], next_cursor="c1"))
    result, record = env.run_worker(page(removed=["t1", "never-seen"], next_cursor="c2"))
    assert set(env.txns()) == {"t2"}
    assert env.pointers() == {"t2"}
    assert (result["removed"], record["removed"]) == (1, 1)
    assert record["duplicate"] == 1  # the unknown ID needed no write


def test_an_unusable_transaction_is_counted_and_retried_by_the_next_sync(env):
    env.link()
    broken = {**txn("bad"), "date": None}
    result, record = env.run_worker(page(added=[broken, txn("t1")], next_cursor="c1"))
    assert (result["added"], result["failed"]) == (1, 1)
    assert record["status"] == "complete"
    assert record["errors"][0]["error"] == "transaction has no usable date"
    assert "try them again" in record["errors"][-1]["error"]
    # The cursor did not move past the row that could not be read...
    assert env.cursor() == ""
    assert env.dynamo.get_plaid_item(SUB, ITEM_ID)["lastSyncedAt"]

    # ...so the next sync is sent the same updates again, and this time the row is usable.
    result, _ = env.run_worker(page(added=[txn("bad"), txn("t1")], next_cursor="c1"))
    assert env.plaid.sync_cursors[-1] == ""
    assert (result["added"], result["duplicate"], result["failed"]) == (1, 1, 0)
    assert set(env.txns()) == {"bad", "t1"}
    assert env.cursor() == "c1"


def test_csv_rows_are_untouched_by_a_plaid_sync(env):
    from core.transactions import to_item

    csv_row = {"type": "TXN", "txnId": "0123456789abcdef", "date": "2026-11-10",
               "amountCents": -500, "direction": "debit", "balanceCents": 1000,
               "accountId": "chase-5980", "descriptionRaw": "X", "merchantNormalized": "x",
               "sourceType": "DEBIT_CARD", "raw": {}}
    env.dynamo.put_transaction(SUB, to_item(csv_row, import_id="csv-import"))
    env.link()
    env.run_worker(page(added=[txn("t1")], removed=["0123456789abcdef"], next_cursor="c1"))
    assert set(env.txns()) == {"0123456789abcdef", "t1"}  # no pointer → a CSV row can't be removed


def test_balances_and_last_synced_are_refreshed_on_each_sync(env):
    env.link()
    env.run_worker(page(next_cursor="c1"))
    item = env.dynamo.get_plaid_item(SUB, ITEM_ID)
    assert item["lastSyncedAt"]
    assert item["accounts"][0]["balanceAvailableCents"] == 10000


def test_a_worker_without_a_stored_token_fails_cleanly(env):
    env.link()
    boto3.client("secretsmanager", region_name="us-east-1").put_secret_value(
        SecretId=TOKENS_SECRET, SecretString='{"items":{}}')
    result, record = env.run_worker(page(next_cursor="c1"))
    assert result["status"] == "failed"
    assert "link it again" in record["errors"][0]["error"]


# --- Sandbox test actions ------------------------------------------------------------------


def test_sandbox_link_and_refresh_work_by_direct_invocation(env):
    linked = env.api.handler({"action": "sandbox_link", "sub": SUB,
                              "username": "user_transactions_dynamic"}, None)
    assert linked["ok"] is True
    assert linked["itemId"] == ITEM_ID
    assert ACCESS_TOKEN not in json.dumps(linked)
    refreshed = env.api.handler({"action": "sandbox_refresh", "sub": SUB, "itemId": ITEM_ID}, None)
    assert refreshed == {"ok": True, "plaidRequestId": "req-refresh"}
    assert env.plaid.refreshed == [ACCESS_TOKEN]


def test_sandbox_actions_are_refused_outside_sandbox_and_are_not_http_routes(env):
    env.plaid.plaid_env = "production"
    refused = env.api.handler({"action": "sandbox_link", "sub": SUB}, None)
    assert refused["ok"] is False
    env.plaid.plaid_env = "sandbox"
    status, _, _ = env.api_call("/plaid/sandbox_link", {"action": "sandbox_link"})
    assert status == 404


# --- review fixes (PR #61) -----------------------------------------------------------------


def decision(category_id="cat-food", status="auto"):
    return Decision(category_id=category_id, status=status, confidence=0.95,
                    needs_review=False, source="llm")


def cancelled(*codes) -> ClientError:
    """A TransactionCanceledException with the given per-item reason codes."""
    return ClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
         "CancellationReasons": [{"Code": code} for code in codes]},
        "TransactWriteItems",
    )


def fail_transactions(env, monkeypatch, *errors):
    """Make the next ``len(errors)`` write transactions fail, then behave normally."""
    real = env.dynamo._client.transact_write_items
    queue = list(errors)
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        if queue:
            raise queue.pop(0)
        return real(**kwargs)

    monkeypatch.setattr(env.dynamo._client, "transact_write_items", fake)
    return calls


def test_categorizing_a_row_that_no_longer_exists_writes_nothing(env):
    # The categorizer read a row, then a sync removed it before the write.
    env.link()
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    env.run_worker(page(removed=["t1"], next_cursor="c2"))
    before = env.all_items()
    assert env.dynamo.apply_categorization(SUB, "2026-11-10", "t1", decision()) is False
    assert env.all_items() == before  # no stub row with only category fields


def test_categorizing_under_a_pending_rows_old_key_after_it_posted_writes_nothing(env):
    env.link()
    env.run_worker(page(added=[txn("p1", pending=True, date="2026-11-09")], next_cursor="c1"))
    env.run_worker(page(added=[txn("t1", pending_id="p1")], removed=["p1"], next_cursor="c2"))
    assert env.dynamo.apply_categorization(SUB, "2026-11-09", "p1", decision()) is False
    rows = env.txns()
    assert set(rows) == {"t1"}
    assert all("txnId" in i and "amountCents" in i
               for i in env.all_items() if i["sk"].startswith("TXN#"))
    # The posted row, under its own key, is still categorizable.
    assert env.dynamo.apply_categorization(SUB, "2026-11-10", "t1", decision()) is True


def test_categorizing_under_the_old_date_after_a_row_moved_writes_nothing(env):
    env.link()
    env.run_worker(page(added=[txn("t1", date="2026-11-10")], next_cursor="c1"))
    env.run_worker(page(modified=[txn("t1", date="2026-11-12")], next_cursor="c2"))
    assert env.dynamo.apply_categorization(SUB, "2026-11-10", "t1", decision()) is False
    assert [i["sk"] for i in env.all_items() if i["sk"].startswith("TXN#")] == [
        "TXN#2026-11-12#t1"]


def test_the_connection_is_recorded_before_the_account_list_is_fetched(env):
    seen = {}

    def accounts_get(*, access_token):
        seen["record"] = env.dynamo.get_plaid_item(SUB, ITEM_ID)
        raise PlaidError(error_type="INSTITUTION_ERROR", error_code="INSTITUTION_DOWN",
                         request_id="req-a", status=400, endpoint="/accounts/get")

    env.plaid.accounts_get = accounts_get
    status, body, _ = env.api_call("/plaid/exchange", {
        "publicToken": PUBLIC_TOKEN,
        "institution": {"id": "ins_109508", "name": "First Platypus Bank"}})
    # The record existed before the call that failed, and the link still succeeds.
    assert seen["record"]["itemId"] == ITEM_ID
    assert status == 201
    assert (body["itemId"], body["accounts"]) == (ITEM_ID, [])
    assert body["institutionName"] == "First Platypus Bank"
    assert len(env.started) == 1
    assert env.plaid.exchanged == [PUBLIC_TOKEN]  # exchanged once, never again


def test_a_connection_linked_without_accounts_gets_them_from_its_first_sync(env):
    real_accounts_get = env.plaid.accounts_get

    def down(*, access_token):
        raise PlaidError(error_type="INSTITUTION_ERROR", error_code="INSTITUTION_DOWN",
                         request_id="req-a", status=400, endpoint="/accounts/get")

    env.plaid.accounts_get = down
    env.link()
    env.plaid.accounts_get = real_accounts_get
    env.plaid.script = [page(added=[txn("t1")], next_cursor="c1")]
    env.worker.handler(env.started[-1], None)
    assert env.dynamo.get_plaid_item(SUB, ITEM_ID)["accounts"][0]["accountId"] == (
        "plaid-checking-0000")
    assert env.txns()["t1"]["accountId"] == "plaid-checking-0000"


def test_a_failed_record_write_is_logged_with_the_item_id_and_never_the_token(
        env, monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def boom(sub, record):
        raise RuntimeError("dynamo unavailable")

    monkeypatch.setattr(env.api, "put_plaid_item", boom)
    with pytest.raises(RuntimeError):
        env.api_call("/plaid/exchange", {"publicToken": PUBLIC_TOKEN})
    assert "token_stored_without_item_record" in caplog.text
    assert ITEM_ID in caplog.text
    assert ACCESS_TOKEN not in caplog.text


def test_a_throttled_insert_is_an_error_not_an_already_exists(env, monkeypatch):
    env.link()
    calls = fail_transactions(env, monkeypatch, *[cancelled("ThrottlingError", "None")] * 4)
    result, record = env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    assert len(calls) == 4  # retried, then gave up
    assert result["status"] == "failed"
    assert record["status"] == "failed"
    assert env.txns() == {}
    assert env.cursor() == ""  # so the next sync delivers t1 again

    result, _ = env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    assert result["added"] == 1


def test_a_transient_conflict_is_retried_and_the_row_is_written(env, monkeypatch):
    env.link()
    calls = fail_transactions(env, monkeypatch, cancelled("TransactionConflict", "None"))
    result, _ = env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    assert len(calls) == 2
    assert (result["added"], result["duplicate"]) == (1, 0)
    assert set(env.txns()) == {"t1"}


def test_a_conflict_during_a_merge_never_deletes_the_pending_row_alone(env, monkeypatch):
    env.link()
    env.run_worker(page(added=[txn("p1", pending=True)], next_cursor="c1"))
    env.categorize("p1", "cat-food")
    calls = fail_transactions(
        env, monkeypatch,
        *[cancelled("None", "None", "TransactionConflict", "None")] * 4)
    result, _ = env.run_worker(
        page(added=[txn("t1", pending_id="p1")], removed=["p1"], next_cursor="c2"))
    assert len(calls) == 4  # the merge only - no follow-up "drop the pending row" write
    assert result["status"] == "failed"
    assert set(env.txns()) == {"p1"}
    assert env.pointers() == {"p1"}
    assert env.cursor() == "c1"

    # The replay completes the merge and the owner's category survives.
    result, _ = env.run_worker(
        page(added=[txn("t1", pending_id="p1")], removed=["p1"], next_cursor="c2"))
    rows = env.txns()
    assert set(rows) == {"t1"}
    assert (rows["t1"]["categoryId"], rows["t1"]["categoryStatus"]) == ("cat-food", "corrected")


def test_a_condition_failure_on_any_item_but_the_guarded_put_is_not_already_exists(
        env, monkeypatch):
    calls = fail_transactions(env, monkeypatch, cancelled("None", "ConditionalCheckFailed"))
    with pytest.raises(ClientError):
        env.dynamo._transact([{"Put": {}}, {"Put": {}}])
    assert len(calls) == 1  # not transient, so not retried either


def test_a_genuinely_existing_row_is_still_reported_as_a_duplicate(env):
    # Against moto's real cancellation reasons, not a hand-built error.
    env.link()
    env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    row = {k: v for k, v in env.txns()["t1"].items() if k not in ("pk", "sk")}
    assert env.dynamo.insert_plaid_transaction(SUB, row) is False


def test_a_misconfigured_plaid_environment_is_a_503_not_a_400(env, monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "production")
    env.api._plaid = None  # force the real client to be built
    status, body, _ = env.api_call("/plaid/link-token")
    assert status == 503
    assert body == {"message": "Bank connections are not configured."}
    refused = env.api.handler({"action": "sandbox_link", "sub": SUB}, None)
    assert refused["ok"] is False


def test_unknown_paths_are_404(env):
    status, _, _ = env.api_call("/plaid/nope")
    assert status == 404


def destination_event(payload) -> dict:
    return {"version": "1.0", "requestContext": {"condition": "RetriesExhausted"},
            "requestPayload": payload, "responseContext": {"functionError": "Unhandled"},
            "responsePayload": {"errorMessage": "Task timed out after 180.00 seconds"}}


def test_a_sync_that_died_twice_is_marked_failed_instead_of_parsing_forever(env):
    on_failure = importlib.import_module("functions.plaid_sync.on_failure")
    env.link()
    _, body, _ = env.api_call("/plaid/sync")
    import_id = body["imports"][0]["importId"]
    env.dynamo.set_import_status(SUB, import_id, "parsing")  # the worker got this far, then died

    assert on_failure.handler(destination_event(env.started[-1]), None) == {"marked": True}
    record = env.dynamo.get_import(SUB, import_id)
    assert record["status"] == "failed"
    assert "did not finish" in record["errors"][0]["error"]
    assert env.cursor() == ""


def test_the_failure_handler_never_overwrites_a_finished_import_or_invents_one(env):
    on_failure = importlib.import_module("functions.plaid_sync.on_failure")
    env.link()
    _, record = env.run_worker(page(added=[txn("t1")], next_cursor="c1"))
    assert record["status"] == "complete"
    assert on_failure.handler(destination_event(env.started[-1]), None) == {"marked": False}
    assert env.dynamo.get_import(SUB, record["importId"])["status"] == "complete"

    ghost = {"sub": SUB, "itemId": ITEM_ID, "importId": "no-such-import"}
    assert on_failure.handler(destination_event(ghost), None) == {"marked": False}
    assert env.dynamo.get_import(SUB, "no-such-import") is None
    assert on_failure.handler({"requestPayload": "garbage"}, None) == {"marked": False}
