"""Plaid sync worker (async-invoked) — pull one Item's updates into the ledger (ADR-014).

Invoked asynchronously by the ``api_plaid`` Lambda with locate keys only::

    {"sub": "<owner sub>", "itemId": "<Plaid item_id>", "importId": "<ulid>"}

Flow:

  1. load the Item record (cursor) and the access token (Secrets Manager); import → parsing
  2. page ``/transactions/sync`` **to the end, buffering everything**; if Plaid reports the
     data changed mid-pagination, restart from the cursor this sync began with
  3. plan the buffered added / modified / removed, then apply them — posted rows that replace
     a pending row first, removals last
  4. save the new cursor (and the accounts' cached balances) — only after every write landed,
     and only if every row could be read (a row that could not be is retried by the next sync
     rather than skipped for good)
  5. import → complete with counts; enqueue the new rows for categorization (best-effort)

**Why the cursor is saved last, and not in one transaction with the writes.** A first sync can
write hundreds of rows, more than a DynamoDB transaction holds. Instead every write is
idempotent (conditional insert, compare-then-update, delete-if-present), so if this Lambda
dies before step 4 the next sync replays the same updates from the old cursor and converges
on the same state. Saving the cursor *early* is the one ordering that loses data.

**When the worker never reports.** A handled failure marks the import ``failed`` here. A
timeout or crash cannot, so Lambda retries once and, if that also dies, sends the original
event to the ``on_failure`` handler in this package, which marks the import failed instead of
leaving it "parsing" forever.

The access token is read, passed to the Plaid adapter, and never logged, stored in the table,
or put in the import record.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from adapters.dynamo import (
    delete_plaid_transaction,
    get_plaid_item,
    get_plaid_txn_date,
    insert_plaid_transaction,
    merge_pending_transaction,
    save_plaid_sync_state,
    set_import_status,
    set_plaid_item_error,
    update_plaid_transaction,
)
from adapters.plaid import PlaidClient, PlaidError, is_mutation_during_pagination
from adapters.secrets import SecretConfigError, get_access_token, get_plaid_credentials
from adapters.sqs import enqueue_categorization
from core.imports import STATUS_COMPLETE, STATUS_FAILED, STATUS_PARSING
from core.plaid_items import account_labels, account_types, account_view
from core.plaid_normalize import normalize
from core.plaid_sync import OP_MERGE, OP_REMOVE, collect_updates, plan
from core.transactions import STATUS_UNCATEGORIZED, to_item

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Built on first use so a cold start never touches Secrets Manager unless a sync runs; tests
# replace it with a fake.
_plaid: PlaidClient | None = None


def _client() -> PlaidClient:
    global _plaid
    if _plaid is None:
        _plaid = PlaidClient(
            plaid_env=os.environ.get("PLAID_ENV", ""),
            credentials=get_plaid_credentials,
        )
    return _plaid


class SyncFailedError(Exception):
    """A sync that cannot proceed, with a message that is safe to show the owner."""


def handler(event: dict, context) -> dict:
    sub, item_id, import_id = event["sub"], event["itemId"], event["importId"]
    try:
        counts = _sync(sub, item_id, import_id)
    except Exception as err:
        # Nothing has been half-applied in a way a re-run can't finish (see module docstring),
        # and the cursor is unchanged, so the owner's remedy is simply "Sync now" again.
        message = _owner_message(err)
        plaid_fields = err.log_fields() if isinstance(err, PlaidError) else {}
        logger.exception(json.dumps({
            "stage": "plaid_sync", "importId": import_id, "itemId": item_id,
            "outcome": "failed", "reason": message, **plaid_fields,
        }))
        set_import_status(sub, import_id, STATUS_FAILED, errors=[{"error": message}])
        if isinstance(err, PlaidError) and not err.retryable:
            # Shown on the connections panel; ITEM_LOGIN_REQUIRED there offers "Reconnect".
            # Transient errors are not recorded: they clear on their own.
            try:
                set_plaid_item_error(sub, item_id, error_code=err.error_code,
                                     at=datetime.now(UTC).isoformat())
            except Exception:
                logger.exception(json.dumps({"stage": "plaid_sync", "itemId": item_id,
                                             "err": "could not record the item error"}))
        return {"status": STATUS_FAILED, "importId": import_id}
    return {"status": STATUS_COMPLETE, "importId": import_id, **counts}


def _owner_message(err: Exception) -> str:
    """A failure description with no secret material in it, by construction."""
    if isinstance(err, PlaidError):
        return f"Plaid error {err.error_code} (request {err.request_id or 'unknown'})"
    if isinstance(err, SyncFailedError | SecretConfigError):
        return str(err)
    return "sync failed unexpectedly - see the plaid-sync logs"


def _sync(sub: str, item_id: str, import_id: str) -> dict:
    item = get_plaid_item(sub, item_id)
    if item is None:
        raise SyncFailedError("this bank connection is not known")
    access_token = get_access_token(sub, item_id)
    if access_token is None:
        raise SyncFailedError("no stored access for this bank connection - link it again")

    set_import_status(sub, import_id, STATUS_PARSING)
    client = _client()
    start_cursor = item.get("cursor", "")

    updates = collect_updates(
        lambda cursor: client.transactions_sync(access_token=access_token, cursor=cursor),
        start_cursor,
        is_mutation_error=is_mutation_during_pagination,
    )

    # /accounts/get is the authoritative account list, and carries Plaid's cached balances.
    fetched = client.accounts_get(access_token=access_token).get("accounts") or []
    accounts = [account_view(a) for a in fetched] or item.get("accounts", [])
    labels = account_labels(accounts)
    # Stored types first, fresh ones over them: an account /accounts/get stops returning (a
    # closed loan) must not lose its type on a `modified` row, or that row's loan payment
    # would start counting as income again (accountType is a source field, so an absent
    # value is removed).
    types = {**account_types(item.get("accounts", [])), **account_types(accounts)}

    added = modified = merged = removed = skipped = pending_added = 0
    errors: list[dict] = []
    enqueue_keys: list[dict] = []
    merged_pending_ids: set[str] = set()

    for op in plan(updates):
        if op.kind == OP_REMOVE:
            if delete_plaid_transaction(sub, op.transaction_id):
                removed += 1
            elif op.transaction_id not in merged_pending_ids:
                skipped += 1  # never stored, or removed by an earlier run of this same sync
            continue

        try:
            normalized = normalize(op.txn, account_labels=labels, item_id=item_id,
                                   plaid_env=client.plaid_env, account_types=types)
        except ValueError as err:
            errors.append({"error": str(err)})
            continue
        body = to_item(normalized, import_id=import_id)
        key = {"date": body["date"], "txnId": body["txnId"]}

        if op.kind == OP_MERGE:
            outcome, status = merge_pending_transaction(
                sub, body, pending_transaction_id=op.transaction_id
            )
            if outcome == "merged":
                merged += 1
                merged_pending_ids.add(op.transaction_id)
                if status == STATUS_UNCATEGORIZED:
                    enqueue_keys.append(key)  # the pending row had not been categorized yet
                continue
            # The pending row is not stored: the posted row is simply new (or already here).

        stored_date = get_plaid_txn_date(sub, body["txnId"])
        outcome = "missing"
        if stored_date is not None:
            outcome, status = update_plaid_transaction(sub, body, stored_date=stored_date)
            if outcome == "updated":
                modified += 1
                if status == STATUS_UNCATEGORIZED:
                    enqueue_keys.append(key)  # its key may have changed with its date
            elif outcome == "unchanged":
                skipped += 1
        if outcome == "missing":
            if insert_plaid_transaction(sub, body):
                added += 1
                pending_added += 1 if body.get("pending") else 0
                enqueue_keys.append(key)
            else:
                skipped += 1

    # A row that could not be read must not be left behind: Plaid never re-sends what lies
    # before the cursor. So when any row failed, the cursor stays where this sync started and
    # the next sync replays the same updates - every write above is idempotent, so the good
    # rows are no-ops and only the failed ones are attempted again. The balances are still
    # refreshed (same cursor in, same cursor out).
    cursor_saved = save_plaid_sync_state(
        sub, item_id,
        previous_cursor=start_cursor,
        cursor=start_cursor if errors else updates.next_cursor,
        accounts=accounts,
        synced_at=datetime.now(UTC).isoformat(),
    )
    failed = len(errors)
    cursor_held = failed > 0
    if cursor_held:
        errors.append({"error": f"{failed} transaction(s) could not be read; "
                                "the next sync will try them again"})

    counts = {
        "added": added, "modified": modified + merged, "removed": removed,
        "duplicate": skipped, "failed": failed,
    }
    set_import_status(sub, import_id, STATUS_COMPLETE, errors=errors, **counts)
    logger.info(json.dumps({
        "stage": "plaid_sync", "importId": import_id, "itemId": item_id, "outcome": "complete",
        **counts, "merged": merged, "pendingAdded": pending_added,
        "pages": updates.pages, "restarts": updates.restarts, "cursorSaved": cursor_saved,
        "cursorHeld": cursor_held,
        "plaidRequestIds": updates.request_ids[-3:],  # safe to log; Plaid support needs them
    }))

    # Hand new rows to the categorizer. Best-effort, exactly like the CSV importer: the rows
    # are already saved as Uncategorized, so a lost enqueue costs a re-drive, never data.
    try:
        enqueue_categorization(sub, enqueue_keys)
    except Exception:
        logger.exception(json.dumps({
            "stage": "plaid_sync", "importId": import_id, "err": "enqueue_categorization failed"
        }))
    return {**counts, "merged": merged, "pendingAdded": pending_added}
