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
STATUS_AUTO = "auto"            # categorized by the pipeline (rule or LLM), Slice 5 (FR-3)
STATUS_CONFIRMED = "confirmed"  # owner confirmed the auto category, Slice 7 (FR-6.3)
STATUS_CORRECTED = "corrected"  # owner changed the category, Slice 7 (FR-3.4/6.2)

# Statuses the categorizer must never overwrite — the owner's own decisions win over any
# re-run of the pipeline (architecture §3.2 guard; makes re-processing correction-preserving).
OWNER_SET_STATUSES = (STATUS_CONFIRMED, STATUS_CORRECTED)


def txn_sk(date: str, txn_id: str) -> str:
    """Sort key ``TXN#<date>#<txnId>`` — date-ordered within the user partition (§2.4)."""
    return f"TXN#{date}#{txn_id}"


def gsi1_keys(sub: str, category_id: str, date: str, txn_id: str) -> dict:
    """GSI1 keys for category drill-down (AP 8) — present once a txn has a category.

    ``gsi1pk = USER#<sub>#CAT#<catId>`` / ``gsi1sk = TXN#<date>#<txnId>`` (architecture §2.4).
    """
    return {
        "gsi1pk": f"USER#{sub}#CAT#{category_id}",
        "gsi1sk": txn_sk(date, txn_id),
    }


def gsi2_keys(sub: str, date: str, txn_id: str) -> dict:
    """GSI2 keys for the review queue (AP 9), sparse — present only while ``needsReview``.

    ``gsi2pk = USER#<sub>#REVIEW`` / ``gsi2sk = TXN#<date>#<txnId>`` (architecture §2.4).
    """
    return {
        "gsi2pk": f"USER#{sub}#REVIEW",
        "gsi2sk": txn_sk(date, txn_id),
    }


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
        # confidence is a float; needsReview surfaces the txn in the review queue (Slice 7).
        "confidence": float(item["confidence"]) if item.get("confidence") is not None else None,
        "needsReview": bool(item.get("needsReview", False)),
        "importId": item.get("importId", ""),
    }
