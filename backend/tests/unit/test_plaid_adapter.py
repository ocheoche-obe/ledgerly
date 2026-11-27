"""Tests for the Plaid HTTP adapter and the Secrets Manager adapter (ADR-014).

The Plaid transport is faked — no network. What is being pinned is the handling of secret
material: the keys go in headers and never in a body, errors carry no request or response
content, and only Sandbox is reachable.
"""
from __future__ import annotations

import importlib
import itertools
import json
import sys
import urllib.error

import boto3
import pytest
from moto import mock_aws

from adapters.plaid import PlaidClient, PlaidError, base_url, is_mutation_during_pagination

CLIENT_ID = "test-client-id-0000"
SECRET = "test-secret-do-not-leak"
ACCESS_TOKEN = "access-sandbox-test-token"


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return status, json.dumps(body).encode()


def make_client(*responses) -> tuple[PlaidClient, FakeTransport]:
    transport = FakeTransport(*responses)
    client = PlaidClient(plaid_env="sandbox", credentials=lambda: (CLIENT_ID, SECRET),
                         transport=transport, sleep=lambda _s: None)
    return client, transport


def body_of(request) -> dict:
    return json.loads(request.data)


def test_only_sandbox_and_production_are_reachable():
    assert base_url("sandbox") == "https://sandbox.plaid.com"
    assert base_url("production") == "https://production.plaid.com"
    for env in ("development", "", "SANDBOX", "Production", "prod"):
        with pytest.raises(ValueError, match="sandbox"):
            PlaidClient(plaid_env=env, credentials=lambda: ("a", "b"))


def test_new_links_ask_for_two_years_of_history_and_update_mode_does_not():
    client, transport = make_client((200, {"link_token": "a"}), (200, {"link_token": "b"}))
    client.link_token_create(client_user_id="sub-1")
    client.link_token_create(client_user_id="sub-1", access_token=ACCESS_TOKEN)
    new, update = (body_of(r) for r in transport.requests)
    assert new["transactions"] == {"days_requested": 730}
    assert "transactions" not in update


def test_the_oauth_redirect_is_sent_only_when_configured():
    client, transport = make_client((200, {"link_token": "a"}), (200, {"link_token": "b"}),
                                    (200, {"link_token": "c"}))
    client.link_token_create(client_user_id="sub-1")
    client.link_token_create(client_user_id="sub-1", redirect_uri="https://site.example/oauth/plaid")
    client.link_token_create(client_user_id="sub-1", access_token=ACCESS_TOKEN,
                             redirect_uri="https://site.example/oauth/plaid")
    plain, oauth, repair = (body_of(r) for r in transport.requests)
    assert "redirect_uri" not in plain
    assert oauth["redirect_uri"] == "https://site.example/oauth/plaid"
    assert repair["redirect_uri"] == "https://site.example/oauth/plaid"


@pytest.mark.parametrize("call", [
    lambda c: c.sandbox_public_token_create(institution_id="ins_1", username="u", password="p"),
    lambda c: c.sandbox_item_reset_login(access_token=ACCESS_TOKEN),
    lambda c: c.transactions_refresh(access_token=ACCESS_TOKEN),
])
def test_sandbox_only_calls_are_refused_on_a_production_client(call):
    transport = FakeTransport()
    client = PlaidClient(plaid_env="production", credentials=lambda: (CLIENT_ID, SECRET),
                         transport=transport, sleep=lambda _s: None)
    with pytest.raises(ValueError, match="Sandbox-only"):
        call(client)
    assert transport.requests == []  # refused before any request was built


def test_keys_travel_in_headers_and_never_in_the_body():
    client, transport = make_client((200, {"link_token": "link-sandbox-x", "request_id": "r"}))
    client.link_token_create(client_user_id="sub-1")
    request = transport.requests[0]
    assert request.full_url == "https://sandbox.plaid.com/link/token/create"
    assert request.get_header("Plaid-client-id") == CLIENT_ID
    assert request.get_header("Plaid-secret") == SECRET
    assert CLIENT_ID not in request.data.decode()
    assert SECRET not in request.data.decode()


def test_link_token_requests_transactions_only_with_identity_consented():
    client, transport = make_client((200, {"link_token": "x"}))
    client.link_token_create(client_user_id="sub-1")
    body = body_of(transport.requests[0])
    assert body["products"] == ["transactions"]
    assert body["additional_consented_products"] == ["identity"]
    assert body["user"] == {"client_user_id": "sub-1"}
    assert body["country_codes"] == ["US"]
    assert "webhook" not in body


def test_sync_sends_max_page_size_and_omits_an_empty_cursor():
    client, transport = make_client((200, {"has_more": False}), (200, {"has_more": False}))
    client.transactions_sync(access_token=ACCESS_TOKEN, cursor="")
    client.transactions_sync(access_token=ACCESS_TOKEN, cursor="abc")
    first, second = (body_of(r) for r in transport.requests)
    assert first["count"] == 500
    assert "cursor" not in first
    assert first["options"] == {"include_original_description": True}
    assert second["cursor"] == "abc"


def test_amounts_are_parsed_as_decimals_not_floats():
    client, _ = make_client((200, {"added": [{"amount": 12.34}], "has_more": False}))
    amount = client.transactions_sync(access_token=ACCESS_TOKEN, cursor="")["added"][0]["amount"]
    assert str(amount) == "12.34"
    assert not isinstance(amount, float)


def plaid_error(code, error_type="INVALID_REQUEST", status=400):
    return (status, {"error_type": error_type, "error_code": code,
                     "error_message": f"details mentioning {ACCESS_TOKEN}",
                     "request_id": "req-123"})


def test_errors_carry_code_type_and_request_id_and_nothing_else():
    client, _ = make_client(plaid_error("INVALID_ACCESS_TOKEN", "INVALID_INPUT"))
    with pytest.raises(PlaidError) as caught:
        client.accounts_get(access_token=ACCESS_TOKEN)
    err = caught.value
    assert (err.error_type, err.error_code, err.request_id) == (
        "INVALID_INPUT", "INVALID_ACCESS_TOKEN", "req-123")
    rendered = f"{err} {err!r} {json.dumps(err.log_fields())}"
    assert ACCESS_TOKEN not in rendered
    assert SECRET not in rendered
    assert "details mentioning" not in rendered  # Plaid's message text is not relayed


def test_mutation_during_pagination_is_recognized_by_code_and_not_retried():
    client, transport = make_client(
        plaid_error("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION", "TRANSACTIONS_ERROR"))
    with pytest.raises(PlaidError) as caught:
        client.transactions_sync(access_token=ACCESS_TOKEN, cursor="c")
    assert is_mutation_during_pagination(caught.value)
    assert len(transport.requests) == 1
    assert not is_mutation_during_pagination(RuntimeError("x"))


def test_transient_errors_are_retried_then_succeed():
    client, transport = make_client(
        plaid_error("RATE_LIMIT", "RATE_LIMIT_EXCEEDED", 429),
        plaid_error("INSTITUTION_DOWN", "INSTITUTION_ERROR", 400),  # transient despite the 400
        (200, {"accounts": []}),
    )
    assert client.accounts_get(access_token=ACCESS_TOKEN) == {"accounts": []}
    assert len(transport.requests) == 3


def test_the_exchange_is_sent_once_even_when_the_failure_looks_transient():
    # A public token is single-use: a retry after a lost response would be refused.
    for failure in (urllib.error.URLError("reset"),
                    plaid_error("INTERNAL_SERVER_ERROR", "API_ERROR", 500)):
        client, transport = make_client(failure, (200, {"access_token": ACCESS_TOKEN}))
        with pytest.raises(PlaidError):
            client.item_public_token_exchange(public_token="public-sandbox-x")
        assert len(transport.requests) == 1


def test_permanent_errors_are_not_retried():
    client, transport = make_client(plaid_error("ITEM_LOGIN_REQUIRED", "ITEM_ERROR"))
    with pytest.raises(PlaidError):
        client.accounts_get(access_token=ACCESS_TOKEN)
    assert len(transport.requests) == 1


def test_network_failures_retry_and_then_raise_without_request_details():
    failure = urllib.error.URLError(f"connection reset while sending {ACCESS_TOKEN}")
    client, transport = make_client(failure, failure, failure)
    with pytest.raises(PlaidError) as caught:
        client.accounts_get(access_token=ACCESS_TOKEN)
    assert len(transport.requests) == 3
    assert caught.value.error_code == "NETWORK_ERROR"
    assert caught.value.__cause__ is None
    assert ACCESS_TOKEN not in str(caught.value)


def test_a_non_json_error_body_still_produces_a_plaid_error():
    transport = FakeTransport()
    transport.responses.append((502, "<html>bad gateway</html>"))
    client = PlaidClient(plaid_env="sandbox", credentials=lambda: (CLIENT_ID, SECRET),
                         transport=lambda r, t: (502, b"<html>bad gateway</html>"),
                         sleep=lambda _s: None)
    with pytest.raises(PlaidError) as caught:
        client.accounts_get(access_token=ACCESS_TOKEN)
    assert caught.value.status == 502


def test_sandbox_helpers_use_the_documented_shapes():
    client, transport = make_client((200, {"public_token": "p"}), (200, {"request_id": "r"}))
    client.sandbox_public_token_create(institution_id="ins_109508",
                                       username="user_transactions_dynamic", password="x")
    client.transactions_refresh(access_token=ACCESS_TOKEN)
    create, refresh = transport.requests
    assert create.full_url.endswith("/sandbox/public_token/create")
    assert body_of(create) == {
        "institution_id": "ins_109508",
        "initial_products": ["transactions"],
        "options": {"override_username": "user_transactions_dynamic", "override_password": "x"},
    }
    assert refresh.full_url.endswith("/transactions/refresh")


# --- Secrets Manager adapter ---------------------------------------------------------------

KEYS_SECRET = "ledgerly/test/plaid/api-keys"
TOKENS_SECRET = "ledgerly/test/plaid/access-tokens"
LOCK_TABLE = "ledgerly-test-locks"


@pytest.fixture
def secrets(monkeypatch):
    for name, value in (("AWS_DEFAULT_REGION", "us-east-1"), ("AWS_ACCESS_KEY_ID", "testing"),
                        ("AWS_SECRET_ACCESS_KEY", "testing"), ("AWS_SESSION_TOKEN", "testing"),
                        ("PLAID_KEYS_SECRET_ID", KEYS_SECRET),
                        ("PLAID_TOKENS_SECRET_ID", TOKENS_SECRET),
                        ("TABLE_NAME", LOCK_TABLE)):
        monkeypatch.setenv(name, value)
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=LOCK_TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for name in ("adapters.locks", "adapters.secrets"):
            sys.modules.pop(name, None)
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(Name=TOKENS_SECRET, SecretString='{"items":{}}')
        module = importlib.import_module("adapters.secrets")
        yield module, sm


def test_credentials_are_read_from_the_owner_managed_secret(secrets):
    module, sm = secrets
    sm.create_secret(Name=KEYS_SECRET,
                     SecretString=json.dumps({"client_id": CLIENT_ID, "secret": SECRET}))
    assert module.get_plaid_credentials() == (CLIENT_ID, SECRET)


def test_a_missing_keys_secret_is_a_clear_error(secrets):
    module, _ = secrets
    with pytest.raises(module.SecretConfigError, match="ResourceNotFoundException"):
        module.get_plaid_credentials()


@pytest.mark.parametrize("value", [
    "not json at all " + SECRET,
    json.dumps([CLIENT_ID, SECRET]),
    json.dumps({"client_id": CLIENT_ID}),
    json.dumps({"client_id": "", "secret": SECRET}),
])
def test_a_malformed_keys_secret_never_echoes_its_content(secrets, value):
    module, sm = secrets
    sm.create_secret(Name=KEYS_SECRET, SecretString=value)
    with pytest.raises(module.SecretConfigError) as caught:
        module.get_plaid_credentials()
    assert SECRET not in str(caught.value)
    assert CLIENT_ID not in str(caught.value)
    assert caught.value.__cause__ is None


def test_access_tokens_round_trip_and_are_scoped_to_their_owner(secrets):
    module, sm = secrets
    module.store_access_token("sub-1", "item-1", ACCESS_TOKEN)
    module.store_access_token("sub-1", "item-2", "other-token")
    assert module.get_access_token("sub-1", "item-1") == ACCESS_TOKEN
    assert module.get_access_token("sub-1", "item-2") == "other-token"
    assert module.get_access_token("someone-else", "item-1") is None
    assert module.get_access_token("sub-1", "nope") is None
    stored = json.loads(sm.get_secret_value(SecretId=TOKENS_SECRET)["SecretString"])
    assert set(stored["items"]) == {"item-1", "item-2"}


def test_update_mode_link_token_sends_the_access_token_and_no_products():
    client, transport = make_client((200, {"link_token": "x"}))
    client.link_token_create(client_user_id="sub-1", access_token=ACCESS_TOKEN)
    body = body_of(transport.requests[0])
    assert body["access_token"] == ACCESS_TOKEN
    # Products in update mode would ask for extra consent instead of repairing the login.
    assert "products" not in body
    assert "additional_consented_products" not in body
    assert body["user"] == {"client_user_id": "sub-1"}


def test_item_remove_and_reset_login_use_the_documented_shapes():
    client, transport = make_client((200, {"request_id": "r1"}), (200, {"reset_login": True}))
    client.item_remove(access_token=ACCESS_TOKEN)
    client.sandbox_item_reset_login(access_token=ACCESS_TOKEN)
    remove, reset = transport.requests
    assert remove.full_url.endswith("/item/remove")
    assert body_of(remove) == {"access_token": ACCESS_TOKEN}
    assert reset.full_url.endswith("/sandbox/item/reset_login")
    assert body_of(reset) == {"access_token": ACCESS_TOKEN}


def test_deleting_an_access_token_is_scoped_to_its_owner(secrets):
    module, _ = secrets
    module.store_access_token("sub-1", "item-1", ACCESS_TOKEN)
    module.store_access_token("sub-1", "item-2", "other-token")
    assert module.delete_access_token("someone-else", "item-1") is False
    assert module.get_access_token("sub-1", "item-1") == ACCESS_TOKEN
    assert module.delete_access_token("sub-1", "item-1") is True
    assert module.get_access_token("sub-1", "item-1") is None
    assert module.get_access_token("sub-1", "item-2") == "other-token"
    assert module.delete_access_token("sub-1", "item-1") is False


# --- the token-document lease (backlog B-11) ------------------------------------------------


def test_token_writes_wait_for_a_held_lease_and_never_lose_a_change(secrets, monkeypatch):
    """A writer that started first holds the lease; the second waits for it rather than
    overwriting the document with a stale copy."""
    module, sm = secrets
    locks = module.locks
    module.store_access_token("sub-1", "item-1", ACCESS_TOKEN)

    # Someone else holds the lease. The second writer must wait; when the holder finishes
    # (simulated by releasing on the waiter's first sleep), the waiter proceeds.
    assert locks.try_acquire("plaid-access-tokens", "other", lease_seconds=20, now=1000.0)
    real_held = locks.held

    waited = []

    def held_with_release(name, **kwargs):
        def sleep(_s):
            # While the other writer holds the lease, nothing has been written yet.
            doc = json.loads(sm.get_secret_value(SecretId=TOKENS_SECRET)["SecretString"])
            waited.append(set(doc["items"]))
            locks.release("plaid-access-tokens", "other")
        return real_held(name, sleep=sleep, clock=lambda: 1000.0, **kwargs)

    monkeypatch.setattr(locks, "held", held_with_release)
    module.store_access_token("sub-1", "item-2", "other-token")
    assert waited == [{"item-1"}]
    stored = json.loads(sm.get_secret_value(SecretId=TOKENS_SECRET)["SecretString"])
    assert set(stored["items"]) == {"item-1", "item-2"}


def test_a_lease_held_for_the_whole_wait_writes_nothing(secrets, monkeypatch):
    module, sm = secrets
    locks = module.locks
    # Held by someone else for far longer than the writer will wait.
    assert locks.try_acquire("plaid-access-tokens", "other", lease_seconds=600, now=1000.0)
    ticks = itertools.count(1000)
    real_held = locks.held
    monkeypatch.setattr(locks, "held", lambda name, **kw: real_held(
        name, sleep=lambda _s: None, clock=lambda: float(next(ticks)), **kw))
    with pytest.raises(module.TokenStoreBusy):
        module.store_access_token("sub-1", "item-1", ACCESS_TOKEN)
    stored = json.loads(sm.get_secret_value(SecretId=TOKENS_SECRET)["SecretString"])
    assert stored["items"] == {}


def test_an_expired_lease_is_taken_over_and_only_its_holder_can_release(secrets):
    module, _ = secrets
    locks = module.locks
    assert locks.try_acquire("x", "crashed", lease_seconds=20, now=1000.0)
    assert not locks.try_acquire("x", "next", lease_seconds=20, now=1010.0)  # still live
    assert locks.try_acquire("x", "next", lease_seconds=20, now=1021.0)      # expired
    locks.release("x", "crashed")  # a stale holder cannot free someone else's lease
    assert not locks.try_acquire("x", "third", lease_seconds=20, now=1022.0)
    locks.release("x", "next")
    assert locks.try_acquire("x", "third", lease_seconds=20, now=1022.0)
