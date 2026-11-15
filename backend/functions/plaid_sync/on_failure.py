"""On-failure destination for the Plaid sync worker (ADR-014).

The worker reports its own handled failures. What it cannot report is dying: a timeout or a
crash on the first attempt *and* on Lambda's one automatic retry. Lambda then delivers the
original invocation here, and this marks the import ``failed`` so the UI stops polling an
import that would otherwise read "parsing" forever. Nothing else is touched: the cursor is
unmoved and every write the worker made is idempotent, so the remedy is "Sync now" again.

The event is Lambda's destination envelope; only ``requestPayload`` (the worker's own event:
``{sub, itemId, importId}``) is read. It carries no token and no transaction data.
"""
from __future__ import annotations

import json
import logging

from adapters.dynamo import fail_unfinished_import

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MESSAGE = "the sync did not finish (it timed out or crashed) - try Sync now again"


def handler(event: dict, context) -> dict:
    payload = event.get("requestPayload")
    if not isinstance(payload, dict):
        payload = {}
    sub, import_id = payload.get("sub"), payload.get("importId")
    condition = (event.get("requestContext") or {}).get("condition", "")
    if not (isinstance(sub, str) and sub and isinstance(import_id, str) and import_id):
        logger.error(json.dumps({"stage": "plaid_sync_on_failure", "outcome": "unusable_event",
                                 "condition": condition}))
        return {"marked": False}
    marked = fail_unfinished_import(sub, import_id, _MESSAGE)
    logger.error(json.dumps({
        "stage": "plaid_sync_on_failure", "importId": import_id,
        "itemId": payload.get("itemId", ""), "condition": condition, "marked": marked,
    }))
    return {"marked": marked}
