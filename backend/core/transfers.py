"""Transfers between the owner's own accounts (ADR-017) — pure Python, no AWS imports.

A credit-card payment from checking, or a move into savings, is not spending: the money is
still the owner's. Counted as spend it doubles up (the card's purchases were already spend)
and swamps the dashboard. Plaid labels every transaction with a ``personal_finance_category``
(kept on our row inside ``raw``), and this module decides from that label alone whether a row
is such a move. Matching rows are filed under one system category, ``Transfers``
(``kind = "transfer"``), which ``core.budgets.summarize`` leaves out of every figure.

Deliberately narrow, because a wrong "transfer" hides real spending:

- only Plaid's labels for moves between accounts and card payments (below); not loan or
  mortgage payments, not cash withdrawals, not investment contributions (the owner budgets
  those under Savings & Investments);
- only when Plaid's own confidence is HIGH or VERY_HIGH;
- never when a counterparty is a payment app (Venmo, Zelle, Cash App): paying a friend is
  spending, even though Plaid may call it an account transfer.

Anything else goes to the model as before, which never sees the Transfers category.
"""
from __future__ import annotations

TRANSFER_CATEGORY_ID = "transfers"
TRANSFER_CATEGORY_NAME = "Transfers"
KIND_TRANSFER = "transfer"
KIND_SPEND = "spend"
# Listed after any category the owner is likely to create.
TRANSFER_SORT_ORDER = 10_000

OWN_ACCOUNT_MOVES = frozenset({
    "TRANSFER_IN_ACCOUNT_TRANSFER",
    "TRANSFER_OUT_ACCOUNT_TRANSFER",
    "TRANSFER_IN_SAVINGS",
    "TRANSFER_OUT_SAVINGS",
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT",
})
TRUSTED_CONFIDENCE = frozenset({"HIGH", "VERY_HIGH"})
PERSON_TO_PERSON_COUNTERPARTY_TYPES = frozenset({"payment_app"})


def is_own_account_move(txn: dict) -> bool:
    """Whether Plaid's own labels say this row is money moving between the owner's accounts."""
    raw = txn.get("raw")
    if not isinstance(raw, dict):
        return False  # CSV rows carry no Plaid label
    pfc = raw.get("personal_finance_category")
    if not isinstance(pfc, dict):
        return False
    if pfc.get("detailed") not in OWN_ACCOUNT_MOVES:
        return False
    if pfc.get("confidence_level") not in TRUSTED_CONFIDENCE:
        return False
    counterparties = raw.get("counterparties")
    paying_a_person = isinstance(counterparties, list) and any(
        isinstance(c, dict) and c.get("type") in PERSON_TO_PERSON_COUNTERPARTY_TYPES
        for c in counterparties
    )
    return not paying_a_person


def transfer_category_item() -> dict:
    """The system Transfers category (sans key attributes). The owner may rename or archive
    it; archiving stops new rows being filed there."""
    return {
        "type": "CAT",
        "categoryId": TRANSFER_CATEGORY_ID,
        "name": TRANSFER_CATEGORY_NAME,
        "status": "active",
        "sortOrder": TRANSFER_SORT_ORDER,
        "kind": KIND_TRANSFER,
    }


def transfer_category_ids(categories: list[dict]) -> set[str]:
    return {c["categoryId"] for c in categories if c.get("kind") == KIND_TRANSFER}
