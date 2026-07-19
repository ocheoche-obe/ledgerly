"""Transaction domain logic (FR-2.4) — pure Python, no AWS imports.

Owns the *shape* of a stored transaction and its owner-facing projection. A transaction
keeps both the normalized form Ledgerly works with (date/amount/direction/merchant) and the
raw source row (FR-2.4). The normalized fields are produced by ``csv_normalize`` at import;
this module turns one of those into the persisted item and back into a view.

Everything lands ``Uncategorized`` this slice — the AI categorization pipeline (FR-3,
Slice 5) sets ``categoryId``/``confidence`` and the GSI keys later. So no ``gsi1``/``gsi2``
attributes are written here (GSI1 is populated once categorized; GSI2 only while a txn needs
review — architecture §2.4).
"""
from __future__ import annotations

# categoryStatus enum (architecture §2.6): auto | confirmed | corrected | uncategorized
STATUS_UNCATEGORIZED = "uncategorized"


def txn_sk(date: str, txn_id: str) -> str:
    """Sort key ``TXN#<date>#<txnId>`` — date-ordered within the user partition (§2.4)."""
    return f"TXN#{date}#{txn_id}"


def to_item(normalized: dict, *, import_id: str) -> dict:
    """A normalized transaction (from ``csv_normalize.parse``) → the stored item body.

    Returns the item *without* pk/sk (the adapter adds the partition/sort keys); everything
    else — normalized fields, raw row, import provenance, uncategorized defaults — is here.
    """
    return {
        **normalized,  # type, txnId, date, amountCents, direction, balanceCents,
                       # accountId, descriptionRaw, merchantNormalized, sourceType, raw
        "categoryId": None,
        "categoryStatus": STATUS_UNCATEGORIZED,
        "needsReview": False,
        "importId": import_id,
    }


def txn_view(item: dict) -> dict:
    """Owner-facing projection — drops key attributes, coerces DynamoDB numbers to int."""
    return {
        "txnId": item["txnId"],
        "date": item["date"],
        "amountCents": int(item["amountCents"]),
        "direction": item.get("direction", ""),
        "balanceCents": int(item["balanceCents"]),
        "accountId": item.get("accountId", ""),
        "descriptionRaw": item.get("descriptionRaw", ""),
        "merchantNormalized": item.get("merchantNormalized", ""),
        "categoryId": item.get("categoryId"),
        "categoryStatus": item.get("categoryStatus", STATUS_UNCATEGORIZED),
        "importId": item.get("importId", ""),
    }
