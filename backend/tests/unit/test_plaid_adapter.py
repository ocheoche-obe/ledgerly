"""Tests for the Plaid HTTP adapter and the Secrets Manager adapter (ADR-014).

The Plaid transport is faked — no network. What is being pinned is the handling of secret
material: the keys go in headers and never in a body, errors carry no request or response
content, and only Sandbox is reachable.
"""
from __future__ import annotations

import importlib
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


def test_only_sandbox_is_reachable():
    assert base_url("sandbox") == "https://sandbox.plaid.com"
    for env in ("production", "development", "", "SANDBOX"):
        with pytest.raises(ValueError, match="sandbox"):
            PlaidClient(plaid_env=env, credentials=lambda: ("a", "b"))


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


@pytest.fixture
def secrets(monkeypatch):
    for name, value in (("AWS_DEFAULT_REGION", "us-east-1"), ("AWS_ACCESS_KEY_ID", "testing"),
                        ("AWS_SECRET_ACCESS_KEY", "testing"), ("AWS_SESSION_TOKEN", "testing"),
                        ("PLAID_KEYS_SECRET_ID", KEYS_SECRET),
                        ("PLAID_TOKENS_SECRET_ID", TOKENS_SECRET)):
        monkeypatch.setenv(name, value)
    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(Name=TOKENS_SECRET, SecretString='{"items":{}}')
        sys.modules.pop("adapters.secrets", None)
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
