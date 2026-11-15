"""Plaid Item domain logic (ADR-014) — pure Python, no AWS imports.

An *Item* is one login at one institution. Ledgerly keeps one ``PLAIDITEM#<itemId>`` record
per Item holding what a sync needs and what the UI shows: the institution, the accounts with
their last-synced cached balances, and the ``/transactions/sync`` cursor.

**The access token is never part of this record** — it lives in Secrets Manager, so it is not
in the table, not in point-in-time backups, and not readable by every Lambda with table
access. Nothing in this module accepts, stores or returns one.
"""
from __future__ import annotations

from decimal import Decimal

from core.accounts import MAX_LABEL_LEN, normalize_account_id


def plaid_item_sk(item_id: str) -> str:
    return f"PLAIDITEM#{item_id}"


def plaid_txn_pointer_sk(transaction_id: str) -> str:
    """Pointer ``PLAIDTXN#<transaction_id>`` → the date in that transaction's sort key.

    Transactions are keyed ``TXN#<date>#<txnId>``, but Plaid's ``removed`` entries carry only
    an ID and a ``modified`` entry may carry a *new* date. The pointer is how either finds the
    stored row.
    """
    return f"PLAIDTXN#{transaction_id}"


def _cents(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    return int((Decimal(str(value)) * 100).to_integral_value())


def account_label(account: dict) -> str:
    """A readable, stable ``accountId`` for a Plaid account: ``<name>-<mask>``, slugged the
    same way CSV account labels are (``Plaid Checking`` / ``0000`` → ``plaid-checking-0000``).

    Plaid's own ``account_id`` is not used as the label: it is opaque, and it can change when
    an account is renamed at the bank. It is kept alongside as ``plaidAccountId``.
    """
    name = account.get("name") or account.get("official_name") or account.get("subtype") or ""
    mask = account.get("mask") or ""
    label = f"{name} {mask}".strip()[:MAX_LABEL_LEN]
    try:
        return normalize_account_id(label)
    except ValueError:
        return account.get("account_id") or "plaid-account"


def account_view(account: dict) -> dict:
    """One account from Plaid's ``/accounts/get`` → the stored/displayed shape.

    Balances are Plaid's *cached* figures as of its last check of the institution, not a
    real-time balance (that is the separately billed Balance product, out of scope).
    """
    balances = account.get("balances") or {}
    return {
        "plaidAccountId": account.get("account_id") or "",
        "accountId": account_label(account),
        "name": account.get("name") or "",
        "officialName": account.get("official_name") or "",
        "mask": account.get("mask") or "",
        "type": account.get("type") or "",
        "subtype": account.get("subtype") or "",
        "balanceCurrentCents": _cents(balances.get("current")),
        "balanceAvailableCents": _cents(balances.get("available")),
        "currency": balances.get("iso_currency_code")
        or balances.get("unofficial_currency_code")
        or "",
    }


def account_labels(accounts: list[dict]) -> dict[str, str]:
    """Stored account views → ``{plaidAccountId: accountId}`` for the normalizer."""
    return {a["plaidAccountId"]: a["accountId"] for a in accounts if a.get("plaidAccountId")}


def new_plaid_item(
    item_id: str,
    *,
    institution_id: str,
    institution_name: str,
    accounts: list[dict],
    plaid_env: str,
    created_at: str,
    link_session_id: str = "",
) -> dict:
    """A brand-new Item record (sans key attributes). ``accounts`` are Plaid account objects.

    The cursor starts empty, which asks ``/transactions/sync`` for the full available history
    on the first sync.
    """
    return {
        "type": "PLAIDITEM",
        "itemId": item_id,
        "institutionId": institution_id,
        "institutionName": institution_name,
        "accounts": [account_view(a) for a in accounts],
        "plaidEnv": plaid_env,
        "cursor": "",
        "createdAt": created_at,
        "lastSyncedAt": "",
        # Plaid support investigates Link problems by this ID; it is not a secret.
        "linkSessionId": link_session_id,
    }


# Plaid error codes on an Item that the owner fixes by logging in again through Link in
# update mode. Other errors (an institution outage, a rate limit) clear on their own, and
# re-linking would not help them, so they are shown but not offered a "Reconnect" button.
RECONNECT_ERROR_CODES = frozenset({
    "ITEM_LOGIN_REQUIRED",  # the bank login broke or expired (Sandbox Items do this at ~30 days)
    "PENDING_EXPIRATION",   # consent about to expire
    "PENDING_DISCONNECT",   # the institution is about to drop the connection
})


def plaid_item_view(item: dict) -> dict:
    """Owner-facing projection. Deliberately omits the cursor (internal) — and there is no
    token on the record to omit.

    ``errorCode`` is the Plaid error from the most recent failed sync, cleared by the next
    successful one; ``needsReconnect`` says whether Link's update mode is the fix.
    """
    error_code = item.get("errorCode") or ""
    accounts = []
    for a in item.get("accounts", []):
        view = dict(a)
        for key in ("balanceCurrentCents", "balanceAvailableCents"):
            if view.get(key) is not None:
                view[key] = int(view[key])
        accounts.append(view)
    return {
        "itemId": item["itemId"],
        "institutionId": item.get("institutionId", ""),
        "institutionName": item.get("institutionName", ""),
        "accounts": accounts,
        "plaidEnv": item.get("plaidEnv", ""),
        "createdAt": item.get("createdAt", ""),
        "lastSyncedAt": item.get("lastSyncedAt", ""),
        "errorCode": error_code,
        "errorAt": item.get("errorAt", "") if error_code else "",
        "needsReconnect": error_code in RECONNECT_ERROR_CODES,
    }
