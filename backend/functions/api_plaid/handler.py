"""/plaid — connect a bank through Plaid and start syncs (ADR-014; Production on prod, ADR-016).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3).

Routes (all authorized by the API Gateway JWT authorizer):
  POST /plaid/link-token  {itemId?} → {linkToken, expiration, mode}   a short-lived token
                          for Plaid Link; with an itemId it opens Link in *update mode* to
                          repair that connection's login (mode "update"), else a new link
  GET  /plaid/items       → {items: [...]}   connected institutions, accounts, last sync,
                          and any error from the last failed sync (needsReconnect)
  DELETE /plaid/items/{itemId} → {itemId, disconnected: true}   ends the connection at Plaid
                          (/item/remove), forgets the token, deletes the record; the synced
                          transactions are kept (they are history; purging them is separate)
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
    {"action": "sandbox_reset_login", "sub": "...", "itemId": "..."}   → ITEM_LOGIN_REQUIRED
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from adapters.dynamo import (
    create_sync_import,
    delete_plaid_item,
    get_plaid_item,
    list_plaid_items,
    put_plaid_item,
    set_import_status,
    set_plaid_item_accounts,
)
from adapters.lambda_invoke import start_plaid_sync
from adapters.plaid import PlaidClient, PlaidConfigError, PlaidError
from adapters.secrets import (
    SecretConfigError,
    TokenStoreBusy,
    delete_access_token,
    get_access_token,
    get_plaid_credentials,
    store_access_token,
)
from core.ids import new_ulid
from core.imports import STATUS_FAILED
from core.plaid_items import account_view, new_plaid_item, plaid_item_view

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_plaid: PlaidClient | None = None

_ROUTES = frozenset({
    "POST /plaid/link-token", "POST /plaid/exchange", "POST /plaid/sync", "GET /plaid/items",
})
_ITEM_PREFIX = "/plaid/items/"

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

    method, path = _method(event), _path(event)
    route = f"{method} {path}"
    item_route = method == "DELETE" and path.startswith(_ITEM_PREFIX)
    if route not in _ROUTES and not item_route:
        return _response(404, {"message": "Not found"})
    try:
        if item_route:
            route = "DELETE /plaid/items/{itemId}"
            return _disconnect(sub, _item_id_param(event, path))
        if route == "GET /plaid/items":
            return _list_items(sub)
        if route == "POST /plaid/link-token":
            return _link_token(sub, _parse_body(event))
        if route == "POST /plaid/exchange":
            return _exchange(sub, _parse_body(event))
        return _sync(sub, _parse_body(event))
    except PlaidConfigError as err:
        # Checked before ValueError (its base class): a bad PLAID_ENV is this deployment's
        # fault, not the caller's, and the config detail stays in the log.
        logger.error(json.dumps({"route": route, "sub": sub, "err": str(err)}))
        return _response(503, {"message": "Bank connections are not configured."})
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
    except TokenStoreBusy:
        logger.warning(json.dumps({"route": route, "sub": sub, "outcome": "token_store_busy"}))
        return _response(503, {"message": "Another bank change is in progress. Try again in "
                                          "a few seconds."})


# --- routes -----------------------------------------------------------------------------


def _link_token(sub: str, body: dict) -> dict:
    item_id = body.get("itemId")
    if item_id is not None and not isinstance(item_id, str):
        raise ValueError("itemId must be a string")

    access_token = None
    if item_id:
        # Update mode: repair an existing connection's login. Scoped to the caller twice over
        # - the record is read from their partition and the token lookup checks their sub.
        if get_plaid_item(sub, item_id) is None:
            return _response(404, {"message": "bank connection not found"})
        access_token = get_access_token(sub, item_id)
        if access_token is None:
            return _response(409, {"message": "this connection has no stored access; "
                                              "disconnect it and connect the bank again"})

    # The Cognito sub is the stable, non-personal user ID Plaid asks for. The OAuth redirect
    # is configured per stage and must match a URI registered in the Plaid Dashboard.
    result = _client().link_token_create(
        client_user_id=sub, access_token=access_token,
        redirect_uri=os.environ.get("PLAID_REDIRECT_URI") or None,
    )
    logger.info(json.dumps({
        "route": "POST /plaid/link-token", "sub": sub, "mode": "update" if item_id else "link",
        "itemId": item_id or "", "plaidRequestId": result.get("request_id", ""),
    }))
    return _response(200, {
        "linkToken": result["link_token"],
        "expiration": result.get("expiration", ""),
        "mode": "update" if item_id else "link",
    })


def _list_items(sub: str) -> dict:
    items = sorted(list_plaid_items(sub), key=lambda i: i.get("createdAt", ""))
    return _response(200, {"items": [plaid_item_view(i) for i in items]})


def _disconnect(sub: str, item_id: str) -> dict:
    """End a connection: at Plaid first, then our token, then our record.

    The order is what makes a partial failure safe to retry. If ``/item/remove`` fails,
    nothing of ours has changed and the owner can press Disconnect again. If it succeeds and a
    later step fails, a retry finds Plaid answering ``ITEM_NOT_FOUND`` - which means "already
    removed" - and finishes the cleanup. Deleting our record first would orphan a live,
    billable Item whose token nobody could find any more.

    Transactions are kept: they are spending history, and purging Sandbox rows is a separate
    owner decision (ADR-014 tags every Plaid row with its Item for that).
    """
    if not item_id:
        raise ValueError("itemId is required")
    if get_plaid_item(sub, item_id) is None:
        return _response(404, {"message": "bank connection not found"})

    access_token = get_access_token(sub, item_id)
    request_id = ""
    if access_token is not None:
        try:
            request_id = _client().item_remove(access_token=access_token).get("request_id", "")
        except PlaidError as err:
            if err.error_code != "ITEM_NOT_FOUND":
                raise
        delete_access_token(sub, item_id)
    delete_plaid_item(sub, item_id)
    logger.info(json.dumps({
        "route": "DELETE /plaid/items/{itemId}", "sub": sub, "itemId": item_id,
        "hadToken": access_token is not None, "plaidRequestId": request_id,
    }))
    return _response(200, {"itemId": item_id, "disconnected": True})


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


def _remove_unstored_item(client, sub: str, item_id: str, access_token: str) -> None:
    """Best-effort ``/item/remove`` for an Item whose access token could not be stored."""
    try:
        client.item_remove(access_token=access_token)
        outcome = "unstored_item_removed"
    except Exception:  # noqa: BLE001 - best effort on a path that is already failing
        outcome = "unstored_item_remove_failed"
    logger.error(json.dumps({"route": "POST /plaid/exchange", "sub": sub,
                             "itemId": item_id, "outcome": outcome}))


def _link(sub: str, *, public_token: str, institution_id: str, institution_name: str,
          link_session_id: str) -> dict:
    """Exchange a public token, persist the result, and start the first sync.

    A public token is **single-use**: the exchange is attempted once, and once it succeeds
    the connection exists at Plaid and can never be re-derived from the same token. So the
    two things that make it usable are written immediately, before any other call that could
    fail: the access token (Secrets Manager), then the connection record (DynamoDB).
    Everything after that - the account list, the first sync - is best-effort here, because
    the sync worker fetches accounts itself and "Sync now" can always be pressed again.

    The one gap left is a failure *between* those two writes. It is logged with the item ID
    (which is not a secret) so the stored token can be matched to the connection by hand.
    """
    client = _client()
    exchanged = client.item_public_token_exchange(public_token=public_token)
    item_id = exchanged["item_id"]
    access_token = exchanged["access_token"]
    try:
        store_access_token(sub, item_id, access_token)
    except TokenStoreBusy:
        # The public token is spent, so this is the one write that must not be given up on
        # lightly: wait once more for the lease (still inside the Lambda's timeout).
        logger.warning(json.dumps({"route": "POST /plaid/exchange", "sub": sub,
                                   "itemId": item_id, "outcome": "token_store_busy_retry"}))
        try:
            store_access_token(sub, item_id, access_token)
        except TokenStoreBusy:
            # Still busy (a crashed earlier writer can hold the lease for its full 20 s). The
            # token exists only in memory now, so remove the Item at Plaid rather than leave a
            # live connection nobody can reach or disconnect. Connecting again then starts clean.
            _remove_unstored_item(client, sub, item_id, access_token)
            raise

    record = new_plaid_item(
        item_id,
        institution_id=institution_id,
        institution_name=institution_name,
        accounts=[],
        plaid_env=client.plaid_env,
        created_at=datetime.now(UTC).isoformat(),
        link_session_id=link_session_id,
    )
    try:
        created = put_plaid_item(sub, record)
    except Exception:
        logger.exception(json.dumps({
            "route": "POST /plaid/exchange", "sub": sub, "itemId": item_id,
            "outcome": "token_stored_without_item_record",
        }))
        raise
    stored = record if created else (get_plaid_item(sub, item_id) or record)

    try:
        accounts_response = client.accounts_get(access_token=access_token)
    except PlaidError:
        # Already logged by the adapter. The connection is recorded; the first sync fills
        # in the accounts.
        accounts_response = None
    if accounts_response is not None:
        plaid_item = accounts_response.get("item") or {}
        details = {
            "accounts": [account_view(a) for a in accounts_response.get("accounts") or []],
            "institutionId": stored.get("institutionId")
            or str(plaid_item.get("institution_id") or ""),
            "institutionName": stored.get("institutionName")
            or str(plaid_item.get("institution_name") or ""),
        }
        set_plaid_item_accounts(
            sub, item_id, accounts=details["accounts"],
            institution_id=details["institutionId"],
            institution_name=details["institutionName"],
        )
        stored = {**stored, **details}

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
    try:
        client = _client()
    except PlaidConfigError as err:
        return {"ok": False, "error": str(err)}
    if client.plaid_env != "sandbox":
        return {"ok": False, "error": "sandbox actions are disabled outside Plaid Sandbox"}
    sub = event.get("sub")
    if not isinstance(sub, str) or not sub:
        return {"ok": False, "error": "sub is required"}

    action = event["action"]
    try:
        if action == "sandbox_link":
            institution_id = str(event.get("institutionId") or _SANDBOX_DEFAULT_INSTITUTION)
            created = client.sandbox_public_token_create(
                institution_id=institution_id,
                username=str(event.get("username") or "user_good"),
                password=str(event.get("password") or "pass_good"),
            )
            result = _link(sub, public_token=created["public_token"],
                           institution_id=institution_id, institution_name="",
                           link_session_id="")
            return {"ok": True, **result}
        if action == "sandbox_refresh":
            item_id = str(event.get("itemId") or "")
            access_token = get_access_token(sub, item_id)
            if access_token is None:
                return {"ok": False, "error": "no stored access for that itemId"}
            refreshed = client.transactions_refresh(access_token=access_token)
            return {"ok": True, "plaidRequestId": refreshed.get("request_id", "")}
        if action == "sandbox_reset_login":
            item_id = str(event.get("itemId") or "")
            access_token = get_access_token(sub, item_id)
            if access_token is None:
                return {"ok": False, "error": "no stored access for that itemId"}
            reset = client.sandbox_item_reset_login(access_token=access_token)
            return {"ok": True, "plaidRequestId": reset.get("request_id", "")}
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


def _item_id_param(event: dict, path: str) -> str:
    # API Gateway supplies the decoded path parameter; the raw path is the fallback.
    param = (event.get("pathParameters") or {}).get("itemId")
    return str(param if param is not None else path.removeprefix(_ITEM_PREFIX)).strip()


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
