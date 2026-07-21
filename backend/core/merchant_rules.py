"""Merchant-rule domain logic (FR-3.4) — pure Python, no AWS imports.

A merchant rule is the durable form of an owner correction: ``normalizedMerchant → categoryId``
(architecture §2.6). The categorizer checks rules *first* — an exact-match hit skips the LLM
entirely (fast, free, and the learning loop of FR-3.4). This module owns the rule's *shape*
and its key; persistence lives in ``adapters/``.

**This slice reads rules only.** Rule *creation* on correction is Slice 7 (FR-6.2/6.3), so in
Slice 5 the table starts empty and every transaction goes to the LLM. Building the read path
now keeps the pipeline shape complete and the merchant-first fast path real from day one.

Rules key as ``RULE#<normalizedMerchant>`` — the same ``merchantNormalized`` string the CSV
normalizer produces (``core.csv_normalize.normalize_merchant``), so a rule written from one
transaction's merchant matches the next import's identical merchant by exact key equality.
"""
from __future__ import annotations

# How a rule came to exist. Only "correction" exists this MVP; the field is here so a future
# source (bulk import, suggestion-accept) is a value, not a schema change.
SOURCE_CORRECTION = "correction"


def rule_sk(normalized_merchant: str) -> str:
    """Sort key ``RULE#<normalizedMerchant>`` (architecture §2.4). The merchant is already
    normalized/lowercased by ``csv_normalize.normalize_merchant`` — used verbatim as the key."""
    return f"RULE#{normalized_merchant}"


def new_rule(normalized_merchant: str, category_id: str, *, updated_at: str) -> dict:
    """A brand-new merchant-rule item (sans DynamoDB key attributes, which the adapter adds).

    ``updated_at`` is an ISO-8601 timestamp injected by the caller so the shape stays
    deterministic under test. (Write path is Slice 7; provided now so the read path has a
    concrete item shape to round-trip in tests.)
    """
    return {
        "type": "RULE",
        "merchantNormalized": normalized_merchant,
        "categoryId": category_id,
        "source": SOURCE_CORRECTION,
        "hitCount": 0,
        "updatedAt": updated_at,
    }


def rule_category(item: dict | None) -> str | None:
    """The categoryId a rule maps to, or None if there is no rule for the merchant.

    The single seam the categorizer uses: ``rule_category(get_rule(...))`` is either a
    category id (rule hit → skip the LLM) or None (miss → hand the txn to the LLM).
    """
    if not item:
        return None
    return item.get("categoryId") or None
