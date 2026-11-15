"""/plaid — connect a bank through Plaid and start syncs (ADR-014). Sandbox only.

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3).

Routes (all authorized by the API Gateway JWT authorizer):
  POST /plaid/link-token  → {linkToken, expiration}   a short-lived token for Plaid Link
  POST /plaid/exchange    {publicToken, institution?: {id, name}, linkSessionId?}
                          → the new connection (institution + accounts) and the import ID of
                            its first sync
  POST /plaid/sync        {itemId?} → {imports: [{itemId, importId}]}; poll GET /imports/{id}

**What never leaves this Lambda.** The exchange turns Link's one-time public token into a
long-lived access token. That token is written to Secrets Manager and to nothing else: it is
not in any response body, not in any log line, not in DynamoDB. The API keys are read from
Secrets Manager by the Plaid adapter and are never held here at all.

**Sandbox test actions.** Two extra actions exist for exercising the integration without the
Link UI. They are *not* HTTP routes: they answer only to a direct Lambda invocation (which
takes AWS credentials for this account) and only while ``PLAID_ENV`` is ``sandbox``::

    {"action": "sandbox_link", "sub": "...", "institutionId"?, "username"?, "password"?}
    {"action": "sandbox_refresh", "sub": "...", "itemId": "..."}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from adapters.dynamo import (
    create_sync_import,
    get_plaid_item,
    list_plaid_items,
    put_plaid_item,
    set_import_status,
)
from adapters.lambda_invoke import start_plaid_sync
from adapters.plaid import PlaidClient, PlaidError
from adapters.secrets import (
    SecretConfigError,
    get_access_token,
    get_plaid_credentials,
    store_access_token,
)
from core.ids import new_ulid
from core.imports import STATUS_FAILED
from core.plaid_items import new_plaid_item, plaid_item_view

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_plaid: PlaidClient | None = None

# Plaid's Sandbox bank that accepts the special test users (non-OAuth).
_SANDBOX_DEFAULT_INSTITUTION = "ins_109508"  # First Platypus Bank


def _client() -> PlaidClient:
    global _plaid
    if _plaid is None:
        _plaid = PlaidClient(
            plaid_env=os.environ.get("PLAID_ENV", ""),
            credentials=get_plaid_credentials,
            # This Lambda answers a browser through API Gateway (30 s limit): fail fast
            # rather than hold the request open. The sync worker keeps the long defaults.
            timeout=8,
            max_attempts=2,
        )
    return _plaid


def handler(event: dict, context) -> dict:
    if "requestContext" not in event and "action" in event:
        return _sandbox_action(event)

    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/plaid", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    route = f"{_method(event)} {_path(event)}"
    try:
        if route == "POST /plaid/link-token":
            return _link_token(sub)
        if route == "POST /plaid/exchange":
            return _exchange(sub, _parse_body(event))
        if route == "POST /plaid/sync":
            return _sync(sub, _parse_body(event))
    except ValueError as err:
        logger.info(json.dumps({"route": route, "sub": sub, "err": str(err)}))
        return _response(400, {"message": str(err)})
    except PlaidError as err:
        # Already logged by the adapter with its request ID. The error *code* is safe to
        # return and is what the UI would branch on; Plaid's message text is not relayed.
        return _response(502, {
            "message": "The bank connection service returned an error.",
            "errorCode": err.error_code,
            "requestId": err.request_id,
        })
    except SecretConfigError as err:
        logger.error(json.dumps({"route": route, "sub": sub, "err": str(err)}))
        return _response(503, {"message": "Bank connections are not configured."})

    return _response(404, {"message": "Not found"})


# --- routes -----------------------------------------------------------------------------


def _link_token(sub: str) -> dict:
    # The Cognito sub is the stable, non-personal user ID Plaid asks for.
    result = _client().link_token_create(client_user_id=sub)
    logger.info(json.dumps({
        "route": "POST /plaid/link-token", "sub": sub,
        "plaidRequestId": result.get("request_id", ""),
    }))
    return _response(200, {
        "linkToken": result["link_token"],
        "expiration": result.get("expiration", ""),
    })


def _exchange(sub: str, body: dict) -> dict:
    public_token = body.get("publicToken")
    if not isinstance(public_token, str) or not public_token.strip():
        raise ValueError("publicToken is required")
    institution = body.get("institution") if isinstance(body.get("institution"), dict) else {}
    institution_id = str(institution.get("id") or "")

    # Linking the same bank twice creates a second, separately billed connection with fully
    # duplicated transactions — Plaid never dedupes. Refuse before exchanging.
    if institution_id:
        for existing in list_plaid_items(sub):
            if existing.get("institutionId") == institution_id:
                return _response(409, {
                    "message": "This bank is already connected.",
                    "itemId": existing["itemId"],
                })

    result = _link(
        sub,
        public_token=public_token.strip(),
        institution_id=institution_id,
        institution_name=str(institution.get("name") or ""),
        link_session_id=str(body.get("linkSessionId") or ""),
    )
    return _response(201, result)


def _link(sub: str, *, public_token: str, institution_id: str, institution_name: str,
          link_session_id: str) -> dict:
    """Exchange a public token, persist the result, and start the first sync.

    Order matters: the access token is stored *before* anything else, because the exchange is
    the moment the connection exists. If a later step fails, a retry within the public
    token's 30-minute life returns the same connection rather than a second one.
    """
    client = _client()
    exchanged = client.item_public_token_exchange(public_token=public_token)
    item_id = exchanged["item_id"]
    access_token = exchanged["access_token"]
    store_access_token(sub, item_id, access_token)

    accounts_response = client.accounts_get(access_token=access_token)
    plaid_item = accounts_response.get("item") or {}
    record = new_plaid_item(
        item_id,
        institution_id=institution_id or str(plaid_item.get("institution_id") or ""),
        institution_name=institution_name or str(plaid_item.get("institution_name") or ""),
        accounts=accounts_response.get("accounts") or [],
        plaid_env=client.plaid_env,
        created_at=datetime.now(UTC).isoformat(),
        link_session_id=link_session_id,
    )
    created = put_plaid_item(sub, record)
    stored = record if created else (get_plaid_item(sub, item_id) or record)

    # Always sync once at link time: it is also what makes Plaid start tracking updates.
    import_id = _start_sync(sub, stored)
    logger.info(json.dumps({
        "route": "POST /plaid/exchange", "sub": sub, "itemId": item_id, "created": created,
        "accounts": len(stored.get("accounts", [])), "importId": import_id,
        "plaidRequestId": exchanged.get("request_id", ""),
    }))
    return {**plaid_item_view(stored), "importId": import_id}


def _sync(sub: str, body: dict) -> dict:
    item_id = body.get("itemId")
    if item_id is not None and not isinstance(item_id, str):
        raise ValueError("itemId must be a string")
    if item_id:
        item = get_plaid_item(sub, item_id)
        if item is None:
            return _response(404, {"message": "bank connection not found"})
        items = [item]
    else:
        items = list_plaid_items(sub)

    imports = [{"itemId": item["itemId"], "importId": _start_sync(sub, item)} for item in items]
    logger.info(json.dumps({"route": "POST /plaid/sync", "sub": sub, "started": len(imports)}))
    return _response(202, {"imports": imports})


def _start_sync(sub: str, item: dict) -> str:
    """Record a sync as an import and hand it to the worker. Returns the import ID."""
    import_id = new_ulid()
    create_sync_import(
        sub, import_id,
        item_id=item["itemId"],
        institution_name=item.get("institutionName", ""),
        created_at=datetime.now(UTC).isoformat(),
    )
    try:
        start_plaid_sync(sub=sub, item_id=item["itemId"], import_id=import_id)
    except Exception:
        # Don't leave an import "pending" forever when the worker was never started.
        set_import_status(sub, import_id, STATUS_FAILED,
                          errors=[{"error": "the sync could not be started"}])
        raise
    return import_id


# --- Sandbox test actions (direct invocation only) ----------------------------------------


def _sandbox_action(event: dict) -> dict:
    client = _client()
    if client.plaid_env != "sandbox":
        return {"ok": False, "error": "sandbox actions are disabled outside Plaid Sandbox"}
    sub = event.get("sub")
    if not isinstance(sub, str) or not sub:
        return {"ok": False, "error": "sub is required"}

    action = event["action"]
    try:
        if action == "sandbox_link":
            created = client.sandbox_public_token_create(
                institution_id=str(event.get("institutionId") or _SANDBOX_DEFAULT_INSTITUTION),
                username=str(event.get("username") or "user_good"),
                password=str(event.get("password") or "pass_good"),
            )
            result = _link(sub, public_token=created["public_token"], institution_id="",
                           institution_name="", link_session_id="")
            return {"ok": True, **result}
        if action == "sandbox_refresh":
            item_id = str(event.get("itemId") or "")
            access_token = get_access_token(sub, item_id)
            if access_token is None:
                return {"ok": False, "error": "no stored access for that itemId"}
            refreshed = client.transactions_refresh(access_token=access_token)
            return {"ok": True, "plaidRequestId": refreshed.get("request_id", "")}
    except PlaidError as err:
        return {"ok": False, "error": "plaid_error", **err.log_fields()}
    except SecretConfigError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": False, "error": f"unknown action: {action!r}"}


# --- plumbing ---------------------------------------------------------------------------


def _sub_from_event(event: dict) -> str | None:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _method(event: dict) -> str:
    return event.get("requestContext", {}).get("http", {}).get("method", "GET")


def _path(event: dict) -> str:
    return event.get("requestContext", {}).get("http", {}).get("path") or event.get("rawPath", "")


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError("request body must be valid JSON") from err
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
