"""Plaid transaction normalization (ADR-014) — pure Python, no AWS imports.

The Plaid counterpart of ``csv_normalize``: one Plaid transaction object (from
``/transactions/sync``'s ``added`` / ``modified``) → the same normalized dict the rest of
Ledgerly already works with, so nothing downstream of ingest changes (architecture §1.2).

What differs from a CSV row, and why:

- **Identity.** ``txnId`` is Plaid's ``transaction_id`` verbatim — a stable ID Plaid supplies,
  so ADR-012's content hash is neither needed nor possible (there is no running balance).
- **Sign.** Plaid reports money *leaving* the account as positive. Ledgerly stores money out
  as negative (``csv_normalize``), so the amount is negated on the way in.
- **Pending.** A pending charge is stored and flagged. When it posts, Plaid issues a *new*
  ``transaction_id`` that names the pending one in ``pending_transaction_id``; that link is
  kept here so the sync can merge the two into one row.
- **Nulls.** ``merchant_name`` is missing for cash, transfers and fees; ``name`` is the
  fallback. Neither is guaranteed, so nothing here assumes one.
- **No balance.** ``balanceCents`` is absent on Plaid rows.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.csv_normalize import normalize_merchant

SOURCE_PLAID = "plaid"


def _amount_cents(amount) -> int:
    """Plaid amount (a JSON number, positive = money out) → signed cents (negative = out).

    Goes through ``Decimal(str(...))`` so a float such as 12.34 becomes exactly 1234 cents
    rather than 1233.9999….
    """
    if amount is None or isinstance(amount, bool):
        raise ValueError("transaction has no amount")
    try:
        cents = (Decimal(str(amount)) * 100).to_integral_value()
    except InvalidOperation as err:
        raise ValueError("transaction amount is not a number") from err
    return -int(cents)


def dynamo_safe(value):
    """Recursively replace floats with Decimals (DynamoDB rejects Python floats).

    Plaid objects carry floats in a few places beyond ``amount`` (``location.lat``/``lon``),
    and the whole object is kept as ``raw`` (FR-2.4).
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [dynamo_safe(v) for v in value]
    return value


def normalize(
    txn: dict,
    *,
    account_labels: dict[str, str],
    item_id: str,
    plaid_env: str,
    account_types: dict[str, str] | None = None,
) -> dict:
    """One Plaid transaction → a normalized transaction dict (no DynamoDB key attributes).

    ``account_labels`` maps Plaid ``account_id`` → Ledgerly's readable ``accountId``; an
    account the map doesn't know falls back to the Plaid ID. ``account_types`` maps the same
    IDs to Plaid's account ``type`` (``depository``, ``credit``, ``loan``, ...), stamped on the
    row as ``accountType`` so the dashboard can leave loan rows out even after the connection
    is gone. Raises ValueError when the object
    is unusable (no ID, no date, no amount) so the sync can count it rather than crash.
    """
    txn_id = txn.get("transaction_id")
    if not isinstance(txn_id, str) or not txn_id:
        raise ValueError("transaction has no transaction_id")
    date = txn.get("date")
    if not isinstance(date, str) or len(date) != 10:
        raise ValueError("transaction has no usable date")

    amount_cents = _amount_cents(txn.get("amount"))
    plaid_account_id = txn.get("account_id") or ""
    # original_description is the institution's own string (requested via the sync option);
    # `name` is Plaid's cleaned-up form. Prefer the rawest one available.
    description_raw = txn.get("original_description") or txn.get("name") or ""
    merchant_source = txn.get("merchant_name") or txn.get("name") or description_raw

    normalized = {
        "type": "TXN",
        "txnId": txn_id,
        "date": date,
        "amountCents": amount_cents,
        "direction": "credit" if amount_cents > 0 else "debit",
        "accountId": account_labels.get(plaid_account_id, plaid_account_id),
        "descriptionRaw": description_raw,
        "merchantNormalized": normalize_merchant(merchant_source),
        "sourceType": txn.get("payment_channel") or "",
        "pending": bool(txn.get("pending", False)),
        # Provenance: lets every Plaid row be found (and Sandbox rows purged) by query.
        "source": SOURCE_PLAID,
        "plaidEnv": plaid_env,
        "plaidItemId": item_id,
        "plaidAccountId": plaid_account_id,
        "raw": dynamo_safe(txn),
    }
    # Optional attributes are omitted rather than stored as null.
    if txn.get("pending_transaction_id"):
        normalized["pendingTransactionId"] = txn["pending_transaction_id"]
    account_type = (account_types or {}).get(plaid_account_id)
    if account_type:
        normalized["accountType"] = account_type
    if txn.get("authorized_date"):
        normalized["authorizedDate"] = txn["authorized_date"]
    currency = txn.get("iso_currency_code") or txn.get("unofficial_currency_code")
    if currency:
        normalized["currency"] = currency
    return normalized


# The attributes a `modified` update may rewrite. Everything Ledgerly itself decided about a
# transaction — category, status, confidence, review flag, import provenance — is deliberately
# absent, so a Plaid update can never overwrite a categorization or an owner correction.
SOURCE_FIELDS = (
    "amountCents",
    "direction",
    "accountId",
    "descriptionRaw",
    "merchantNormalized",
    "sourceType",
    "pending",
    "plaidAccountId",
    "accountType",
    "raw",
    "pendingTransactionId",
    "authorizedDate",
    "currency",
)

# Source fields an update may change but never remove. `accountType` keeps loan rows out of
# the dashboard; losing it because an account vanished from /accounts/get would be worse
# than keeping the last known type.
STICKY_SOURCE_FIELDS = frozenset({"accountType"})
