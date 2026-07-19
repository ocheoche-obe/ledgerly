"""Unit tests for account identity (core/accounts.py) and the import/transaction
item shapes (core/imports.py, core/transactions.py)."""
from __future__ import annotations

import pytest

from core.accounts import clean_account_label, normalize_account_id
from core.imports import (
    STATUS_COMPLETE,
    STATUS_PENDING,
    import_view,
    new_import,
)
from core.transactions import STATUS_UNCATEGORIZED, to_item, txn_sk, txn_view


# --- account identity (ADR-013) --------------------------------------------------------

@pytest.mark.parametrize(
    "label, expected",
    [
        ("Chase ...5980", "chase-5980"),
        ("  Chase   Checking  ", "chase-checking"),
        ("Amex Gold #1234", "amex-gold-1234"),
    ],
)
def test_normalize_account_id(label, expected):
    assert normalize_account_id(label) == expected


def test_normalize_account_id_is_stable():
    assert normalize_account_id("Chase ...5980") == normalize_account_id("chase 5980")


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_clean_account_label_rejects_empty(bad):
    with pytest.raises(ValueError, match="must not be empty"):
        clean_account_label(bad)


def test_normalize_account_id_rejects_punctuation_only():
    with pytest.raises(ValueError, match="at least one letter or digit"):
        normalize_account_id("...")


# --- import record shape (FR-2.5) ------------------------------------------------------

def test_new_import_starts_pending_with_zero_counts():
    item = new_import(
        "01JIMP", filename="Chase5980.csv", account_label="Chase ...5980",
        account_id="chase-5980", created_at="2026-07-19T12:00:00Z",
    )
    assert item["status"] == STATUS_PENDING
    assert item["added"] == item["duplicate"] == item["failed"] == 0
    assert item["accountLabel"] == "Chase ...5980"
    assert item["accountId"] == "chase-5980"


def test_import_view_marks_done_only_on_terminal_status():
    base = new_import("01JIMP", filename="f.csv", account_label="A",
                      account_id="a", created_at="t")
    assert import_view(base)["done"] is False
    base["status"] = STATUS_COMPLETE
    base["added"] = 42
    view = import_view(base)
    assert view["done"] is True
    assert view["added"] == 42
    assert "pk" not in view and "sk" not in view


def test_import_view_coerces_decimal_counts_to_int():
    from decimal import Decimal

    item = new_import("01JIMP", filename="f.csv", account_label="A",
                      account_id="a", created_at="t")
    item.update(added=Decimal(3), duplicate=Decimal(1), failed=Decimal(0))
    view = import_view(item)
    assert (view["added"], view["duplicate"], view["failed"]) == (3, 1, 0)
    assert all(isinstance(view[k], int) for k in ("added", "duplicate", "failed"))


# --- transaction item shape (FR-2.4) ---------------------------------------------------

def test_txn_sk_is_date_ordered():
    assert txn_sk("2026-07-03", "abc123") == "TXN#2026-07-03#abc123"


def test_to_item_defaults_to_uncategorized_and_carries_import_id():
    normalized = {
        "type": "TXN", "txnId": "abc", "date": "2026-07-03", "amountCents": -675,
        "direction": "debit", "balanceCents": 123256, "accountId": "chase-5980",
        "descriptionRaw": "COFFEE", "merchantNormalized": "coffee", "sourceType": "DEBIT_CARD",
        "raw": {"Amount": "-6.75"},
    }
    item = to_item(normalized, import_id="01JIMP")
    assert item["categoryStatus"] == STATUS_UNCATEGORIZED
    assert item["categoryId"] is None
    assert item["needsReview"] is False
    assert item["importId"] == "01JIMP"
    # No GSI keys until categorized (Slice 5).
    assert "gsi1pk" not in item and "gsi2pk" not in item


def test_txn_view_drops_raw_and_coerces_numbers():
    from decimal import Decimal

    item = {
        "pk": "USER#s", "sk": "TXN#2026-07-03#abc", "txnId": "abc", "date": "2026-07-03",
        "amountCents": Decimal(-675), "direction": "debit", "balanceCents": Decimal(123256),
        "accountId": "chase-5980", "descriptionRaw": "COFFEE", "merchantNormalized": "coffee",
        "categoryId": None, "categoryStatus": "uncategorized", "importId": "01JIMP",
        "raw": {"Amount": "-6.75"},
    }
    view = txn_view(item)
    assert isinstance(view["amountCents"], int) and view["amountCents"] == -675
    assert isinstance(view["balanceCents"], int)
    assert "raw" not in view and "pk" not in view and "sk" not in view
