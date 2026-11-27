"""Secrets Manager adapter (ADR-014) — Ledgerly's only runtime secrets.

Two secrets, both in the stage's own namespace, each read by only the Lambdas that need it:

- **Plaid API keys** (``PLAID_KEYS_SECRET_ID``). Created and filled in by the owner, by hand;
  the stack only *references* it by name, so its value never passes through CDK,
  CloudFormation, the repo or CI. Expected value::

      {"client_id": "<Plaid client_id>", "secret": "<Plaid Sandbox secret>"}

- **Plaid access tokens** (``PLAID_TOKENS_SECRET_ID``). Created empty by the stack and
  written by the exchange Lambda. One JSON document for all Items, so the cost stays at one
  secret however many banks are linked::

      {"items": {"<item_id>": {"sub": "<owner sub>", "accessToken": "<token>"}}}

  Every change is a read-modify-write of that one document, so writers hold a short
  DynamoDB lease (``adapters.locks``) around it: without one, connecting a bank while
  another is being disconnected could silently drop a token (backlog B-11, ADR-016).

Nothing in this module logs, returns to a caller outside the backend, or raises a value read
from either secret. Error messages name the *secret* and the *problem*, never the content.
"""
from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from adapters import locks

_client = boto3.client(
    "secretsmanager",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)

# Cached for the life of the warm container. A key rotation is picked up on the next cold
# start (or sooner: a redeploy). Tokens are not cached — they are read per sync, which is rare.
_credentials_cache: tuple[str, str] | None = None


class SecretConfigError(RuntimeError):
    """A secret is missing, unreadable or not in the expected shape."""


class TokenStoreBusy(RuntimeError):
    """Another change to the access-token document held the lease for the whole wait.
    Nothing was written; the caller can safely try again."""


_TOKENS_LOCK = "plaid-access-tokens"


def _read_json(env_var: str, what: str) -> dict:
    secret_id = os.environ.get(env_var)
    if not secret_id:
        raise SecretConfigError(f"{env_var} is not set")
    try:
        raw = _client.get_secret_value(SecretId=secret_id)["SecretString"]
    except ClientError as err:
        # Only the AWS error *code* is surfaced (e.g. ResourceNotFoundException).
        code = err.response.get("Error", {}).get("Code", "Unknown")
        raise SecretConfigError(f"could not read the {what} secret ({code})") from None
    except KeyError:
        raise SecretConfigError(f"the {what} secret has no string value") from None
    try:
        parsed = json.loads(raw)
    except ValueError:
        # `from None`: a JSON error message can quote the text it failed on.
        raise SecretConfigError(f"the {what} secret is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise SecretConfigError(f"the {what} secret must be a JSON object")
    return parsed


def get_plaid_credentials() -> tuple[str, str]:
    """``(client_id, secret)`` for the Plaid API, from the owner-managed secret."""
    global _credentials_cache
    if _credentials_cache is None:
        parsed = _read_json("PLAID_KEYS_SECRET_ID", "Plaid API keys")
        client_id, secret = parsed.get("client_id"), parsed.get("secret")
        if not (isinstance(client_id, str) and client_id and isinstance(secret, str) and secret):
            raise SecretConfigError(
                'the Plaid API keys secret must be JSON with non-empty "client_id" and "secret"'
            )
        _credentials_cache = (client_id, secret)
    return _credentials_cache


def _items(document: dict) -> dict:
    items = document.get("items")
    return items if isinstance(items, dict) else {}


def get_access_token(sub: str, item_id: str) -> str | None:
    """The stored access token for one of this user's Items, or None.

    The owning ``sub`` is checked, so an Item ID alone can never retrieve another user's token.
    """
    entry = _items(_read_json("PLAID_TOKENS_SECRET_ID", "Plaid access tokens")).get(item_id)
    if not isinstance(entry, dict) or entry.get("sub") != sub:
        return None
    token = entry.get("accessToken")
    return token if isinstance(token, str) and token else None


def store_access_token(sub: str, item_id: str, access_token: str) -> None:
    """Add (or replace) one Item's access token, under the token-document lease."""
    with _tokens_lease():
        document = _read_json("PLAID_TOKENS_SECRET_ID", "Plaid access tokens")
        items = _items(document)
        items[item_id] = {"sub": sub, "accessToken": access_token}
        document["items"] = items
        _write_tokens(document)


def delete_access_token(sub: str, item_id: str) -> bool:
    """Forget one of this user's Items' access token (after ``/item/remove``). False if there
    was none for this user — an Item ID alone can never delete another user's token."""
    with _tokens_lease():
        document = _read_json("PLAID_TOKENS_SECRET_ID", "Plaid access tokens")
        items = _items(document)
        entry = items.get(item_id)
        if not isinstance(entry, dict) or entry.get("sub") != sub:
            return False
        del items[item_id]
        document["items"] = items
        _write_tokens(document)
        return True


def _tokens_lease() -> _Lease:
    return _Lease()


class _Lease:
    """``locks.held`` with its busy error translated into this module's own."""

    def __enter__(self):
        self._inner = locks.held(_TOKENS_LOCK)
        try:
            return self._inner.__enter__()
        except locks.LockBusy:
            raise TokenStoreBusy("the access-token store is busy; try again") from None

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)


def _write_tokens(document: dict) -> None:
    try:
        _client.put_secret_value(
            SecretId=os.environ["PLAID_TOKENS_SECRET_ID"],
            SecretString=json.dumps(document),
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "Unknown")
        raise SecretConfigError(f"could not write the Plaid access tokens secret ({code})") from None
