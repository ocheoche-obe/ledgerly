"""Import-record domain logic (FR-2.5) — pure Python, no AWS imports.

An import is the record of one uploaded file's journey: created when the owner requests an
upload URL, advanced by the import Lambda as it parses, and read back by the UI while it
polls for the result (AP 11). It owns the counts the owner sees — added / duplicate / failed
(FR-2.5) — and the account the file was attributed to (ADR-013). Persistence + the S3 object
live in ``adapters/``; this module only knows the *shape* and the legal status transitions.

Import IDs are ULIDs (``IMPORT#<ulid>``): the ULID's millisecond prefix already sorts by
creation time, so a reverse ``begins_with(sk, 'IMPORT#')`` query lists newest-first (AP 11)
without the separate isoTimestamp the architecture sketch used — same ordering, one token.
"""
from __future__ import annotations

STATUS_PENDING = "pending"    # created; awaiting the file upload / S3 event
STATUS_PARSING = "parsing"    # import Lambda is working the file
STATUS_COMPLETE = "complete"  # rows persisted; counts final
STATUS_DUPLICATE = "duplicate"  # whole file already imported (FILEHASH# hit) — no-op
STATUS_FAILED = "failed"      # the file itself could not be processed

TERMINAL_STATUSES = (STATUS_COMPLETE, STATUS_DUPLICATE, STATUS_FAILED)


def is_terminal(status: str) -> bool:
    """True once an import has reached a final state — used to make a redelivered S3 event
    (at-least-once delivery) a no-op instead of recomputing counts against an already-imported
    file (which would report everything as a duplicate)."""
    return status in TERMINAL_STATUSES


def new_import(import_id: str, *, filename: str, account_label: str, account_id: str,
               created_at: str) -> dict:
    """A brand-new import record (sans DynamoDB key attributes, which the adapter adds).

    ``created_at`` is an ISO-8601 timestamp, injected by the caller so the shape stays
    deterministic under test.
    """
    return {
        "type": "IMPORT",
        "importId": import_id,
        "filename": filename,
        "accountLabel": account_label,
        "accountId": account_id,
        "status": STATUS_PENDING,
        "added": 0,
        "duplicate": 0,
        "failed": 0,
        "errors": [],
        "createdAt": created_at,
    }


def import_view(item: dict) -> dict:
    """Owner-facing projection — drops key attributes, coerces DynamoDB numbers to int."""
    return {
        "importId": item["importId"],
        "filename": item.get("filename", ""),
        "accountLabel": item.get("accountLabel", ""),
        "status": item.get("status", STATUS_PENDING),
        "added": int(item.get("added", 0)),
        "duplicate": int(item.get("duplicate", 0)),
        "failed": int(item.get("failed", 0)),
        "errors": list(item.get("errors", [])),
        "createdAt": item.get("createdAt", ""),
        "done": is_terminal(item.get("status", STATUS_PENDING)),
    }
