"""Plaid sync logic (ADR-014) — pure Python, no AWS imports and no HTTP.

Two pure pieces of the ``/transactions/sync`` flow, kept out of the Lambda so the rules that
decide what ends up in the owner's ledger are testable without AWS or Plaid:

1. :func:`collect_updates` — the pagination loop. Pages are **buffered in memory** and
   nothing is handed back until Plaid says there are no more, because Plaid can change the
   underlying data mid-pagination. When it does, it answers
   ``TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`` and the whole loop must restart from the
   cursor it *started* with — which is only possible if no page was applied on the way.

2. :func:`plan` — turns the buffered ``added`` / ``modified`` / ``removed`` into an ordered
   list of operations, resolving the one genuinely awkward case: a pending charge that posts
   arrives as a *removal* of the pending ID plus an *addition* of a new ID that names it in
   ``pending_transaction_id``. Those two may sit in different pages, in either order, which is
   the other reason pages are buffered.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

MUTATION_DURING_PAGINATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"

# Plaid's maximum page size. Fewer round trips on a first sync, and a narrower window for the
# mid-pagination mutation error.
PAGE_SIZE = 500

# A restart is normal once in a while; many in a row means something else is wrong, and an
# endless loop inside a Lambda is worse than a failed sync the owner can re-run.
MAX_RESTARTS = 5

# Guard against a response that never reports has_more = false.
MAX_PAGES = 200


class SyncRestartsExhaustedError(RuntimeError):
    """Plaid kept mutating the data mid-pagination; the sync gave up without applying anything."""


@dataclass
class Updates:
    """Everything one complete pagination returned, plus the cursor to store afterwards."""

    added: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    next_cursor: str = ""
    pages: int = 0
    restarts: int = 0
    request_ids: list[str] = field(default_factory=list)


def collect_updates(
    fetch_page: Callable[[str], dict],
    start_cursor: str,
    *,
    is_mutation_error: Callable[[Exception], bool],
) -> Updates:
    """Page ``/transactions/sync`` to the end and return everything, or raise.

    ``fetch_page(cursor)`` performs one call and returns Plaid's response dict; an empty
    cursor asks for full history. ``is_mutation_error`` tells this loop which exceptions are
    the mid-pagination mutation (so this module needs no knowledge of the HTTP adapter). Any
    other exception propagates untouched: the caller has applied nothing, and the stored
    cursor is unchanged, so re-running is always safe.
    """
    restarts = 0
    while True:
        updates = Updates(restarts=restarts)
        cursor = start_cursor  # every attempt starts from the cursor the sync began with
        try:
            while True:
                page = fetch_page(cursor)
                updates.pages += 1
                updates.added.extend(page.get("added") or [])
                updates.modified.extend(page.get("modified") or [])
                updates.removed.extend(page.get("removed") or [])
                if page.get("request_id"):
                    updates.request_ids.append(page["request_id"])
                cursor = page.get("next_cursor") or cursor
                if not page.get("has_more"):
                    updates.next_cursor = cursor
                    return updates
                if updates.pages >= MAX_PAGES:
                    raise RuntimeError(f"sync did not finish within {MAX_PAGES} pages")
        except Exception as err:
            if not is_mutation_error(err):
                raise
            restarts += 1
            if restarts > MAX_RESTARTS:
                raise SyncRestartsExhaustedError(
                    f"gave up after {MAX_RESTARTS} pagination restarts"
                ) from err
            # Discard the partial buffer and start over from the original cursor.


# Operation kinds, in the order :func:`plan` emits them.
OP_UPSERT = "upsert"    # added, or modified (the writer decides insert vs. update)
OP_MERGE = "merge"      # a posted row replacing the pending row it grew out of
OP_REMOVE = "remove"


@dataclass(frozen=True)
class Op:
    kind: str
    txn: dict | None = None            # the Plaid transaction (upsert / merge)
    transaction_id: str = ""           # the Plaid ID to remove (remove), or the pending ID (merge)


def plan(updates: Updates) -> list[Op]:
    """Buffered updates → ordered operations.

    Rules:

    - A transaction can appear more than once across pages (added, then modified). The **last**
      version wins, and it is written once.
    - A row whose ``pending_transaction_id`` is set becomes a *merge* — the writer copies the
      pending row's category onto it and deletes the pending row. If the pending row is not in
      the table (it was removed in an earlier sync) the writer falls back to a plain insert.
    - Removals are applied **last**, after every merge has had the chance to read the pending
      row it replaces. A removal of an ID that this same sync also adds or modifies is dropped
      from the upserts — Plaid's final word on that ID is that it is gone.
    """
    removed_ids: list[str] = []
    seen_removed: set[str] = set()
    for entry in updates.removed:
        txn_id = entry.get("transaction_id")
        if txn_id and txn_id not in seen_removed:
            seen_removed.add(txn_id)
            removed_ids.append(txn_id)

    latest: dict[str, dict] = {}  # insertion-ordered: first appearance fixes the position
    for txn in [*updates.added, *updates.modified]:
        txn_id = txn.get("transaction_id")
        if not txn_id:
            continue
        latest[txn_id] = txn

    ops: list[Op] = []
    for txn_id, txn in latest.items():
        if txn_id in seen_removed:
            continue
        pending_id = txn.get("pending_transaction_id")
        if pending_id and not txn.get("pending"):
            ops.append(Op(OP_MERGE, txn=txn, transaction_id=pending_id))
        else:
            ops.append(Op(OP_UPSERT, txn=txn))
    ops.extend(Op(OP_REMOVE, transaction_id=txn_id) for txn_id in removed_ids)
    return ops
