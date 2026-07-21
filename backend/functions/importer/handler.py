"""Import Lambda (S3-triggered) — parse an uploaded CSV into transactions (FR-2).

Triggered by an S3 `ObjectCreated` event on the upload bucket (architecture §3.1). The object
key encodes `<sub>/<importId>.csv`, so identity comes from the key, never from client input.
Flow per file:

  1. resolve sub + importId from the key; load the import record for its accountId
  2. status → parsing
  3. FILEHASH# conditional put — a whole-file re-upload short-circuits to `duplicate` (FR-2.2)
  4. parse rows (malformed rows are counted, never fatal — FR-2.5)
  5. per row: TXN# conditional put → added / duplicate counts (FR-2.2)
  6. status → complete with added/duplicate/failed counts + a sample of errors

Every write is conditional, so a crash + S3 redelivery re-runs harmlessly (NFR-3.2):
`claim_file` recognizes its own prior claim and resumes; transaction puts dedupe.

Categorization (FR-3, Slice 5): once rows are persisted the *newly added* ones are enqueued
for the async categorizer (architecture §3.2). Enqueue is best-effort and never fails the
import — the transactions are already saved as Uncategorized, so a lost enqueue costs a
re-drive at worst, never data (FR-3.5).
"""
from __future__ import annotations

import json
import logging

from adapters.dynamo import (
    claim_file,
    get_import_raw,
    put_transaction,
    set_import_status,
)
from adapters.s3 import get_object_bytes, parse_upload_key
from adapters.sqs import enqueue_categorization
from core.csv_normalize import file_sha256, parse
from core.imports import (
    STATUS_COMPLETE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PARSING,
    is_terminal,
)
from core.transactions import to_item

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    processed = 0
    for record in event.get("Records", []):
        key = record.get("s3", {}).get("object", {}).get("key", "")
        try:
            _process_object(key)
            processed += 1
        except Exception:
            # Log with context and re-raise: a genuine infra failure should hit the Lambda's
            # retry/DLQ path, not be silently swallowed. Row-level problems never reach here
            # (they're counted inside _process_object).
            logger.exception(json.dumps({"stage": "importer", "key": key}))
            raise
    return {"processed": processed}


def _process_object(key: str) -> None:
    sub, import_id = parse_upload_key(key)
    record = get_import_raw(sub, import_id)
    if record is None:
        logger.warning(json.dumps({"stage": "importer", "key": key, "err": "no import record"}))
        return

    if is_terminal(record.get("status", "")):
        # A redelivered S3 event for an import that already finished — no-op, so counts and
        # status aren't recomputed against the file it already imported (FR-2.2 / NFR-3.2).
        logger.info(json.dumps({"stage": "importer", "importId": import_id, "outcome": "already_done"}))
        return

    set_import_status(sub, import_id, STATUS_PARSING)

    data = get_object_bytes(key)

    if not claim_file(sub, file_sha256(data), import_id):
        # This exact file was already imported under a different import — no-op (FR-2.2).
        set_import_status(sub, import_id, STATUS_DUPLICATE)
        logger.info(json.dumps({"stage": "importer", "importId": import_id, "outcome": "duplicate_file"}))
        return

    try:
        content = data.decode("utf-8-sig")  # tolerate a UTF-8 BOM
        result = parse(content, account_id=record["accountId"])
    except (UnicodeDecodeError, ValueError) as err:
        # File-level failure (undecodable bytes or unrecognized format) — the whole file
        # fails, but never crashes the Lambda.
        set_import_status(sub, import_id, STATUS_FAILED, errors=[{"error": str(err)}])
        logger.info(json.dumps({"stage": "importer", "importId": import_id, "outcome": "failed", "err": str(err)}))
        return

    errors = list(result["errors"])
    added_keys: list[dict] = []
    duplicate = 0
    for txn in result["transactions"]:
        if put_transaction(sub, to_item(txn, import_id=import_id)):
            added_keys.append({"date": txn["date"], "txnId": txn["txnId"]})
        else:
            duplicate += 1  # already imported (re-upload / overlapping export)

    added = len(added_keys)
    set_import_status(
        sub, import_id, STATUS_COMPLETE,
        added=added, duplicate=duplicate, failed=len(errors), errors=errors,
    )
    logger.info(json.dumps({
        "stage": "importer", "importId": import_id, "outcome": "complete",
        "added": added, "duplicate": duplicate, "failed": len(errors),
    }))

    # Hand the new rows to the async categorizer (FR-3). Best-effort: a failure here must not
    # fail an import whose transactions are already durably persisted (FR-3.5).
    try:
        enqueue_categorization(sub, added_keys)
    except Exception:
        logger.exception(json.dumps({
            "stage": "importer", "importId": import_id, "err": "enqueue_categorization failed"
        }))
