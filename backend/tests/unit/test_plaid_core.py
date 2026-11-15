"""Pure-logic tests for the Plaid ingest (ADR-014): normalization, the pagination loop, the
operation plan, the Item record, and the pending amounts in the dashboard summary. No AWS, no
HTTP — Plaid responses are plain dicts shaped like the published API reference.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.budgets import summarize
from core.plaid_items import account_view, new_plaid_item, plaid_item_view
from core.plaid_normalize import normalize
from core.plaid_sync import (
    MAX_RESTARTS,
    OP_MERGE,
    OP_REMOVE,
    OP_UPSERT,
    SyncRestartsExhaustedError,
    Updates,
    collect_updates,
    plan,
)
from core.transactions import txn_view


def plaid_txn(txn_id="t1", *, amount=12.34, date="2026-11-10", pending=False,
              pending_id=None, merchant="Starbucks", name="STARBUCKS #123", **extra) -> dict:
    return {
        "transaction_id": txn_id,
        "account_id": "acc-1",
        "amount": amount,
        "iso_currency_code": "USD",
        "date": date,
        "authorized_date": date,
        "name": name,
        "merchant_name": merchant,
        "original_description": None,
        "pending": pending,
        "pending_transaction_id": pending_id,
        "payment_channel": "in store",
        "location": {"lat": 40.7, "lon": -74.0},
        **extra,
    }


def norm(txn: dict) -> dict:
    return normalize(txn, account_labels={"acc-1": "plaid-checking-0000"}, item_id="item-1",
                     plaid_env="sandbox")


# --- normalize ---------------------------------------------------------------------------


def test_money_out_is_positive_at_plaid_and_negative_in_ledgerly():
    out = norm(plaid_txn(amount=12.34))
    assert out["amountCents"] == -1234
    assert out["direction"] == "debit"


def test_money_in_is_negative_at_plaid_and_positive_in_ledgerly():
    out = norm(plaid_txn(amount=-2500.0, merchant=None, name="PAYROLL"))
    assert out["amountCents"] == 250000
    assert out["direction"] == "credit"


@pytest.mark.parametrize(("amount", "cents"), [(0.1, -10), (19.99, -1999), (Decimal("4.35"), -435),
                                              (1234, -123400)])
def test_amounts_become_exact_cents(amount, cents):
    assert norm(plaid_txn(amount=amount))["amountCents"] == cents


def test_txn_id_is_plaids_transaction_id_verbatim():
    assert norm(plaid_txn("AbC-123_xyz"))["txnId"] == "AbC-123_xyz"


def test_null_merchant_falls_back_to_name():
    out = norm(plaid_txn(merchant=None, name="ATM WITHDRAWAL  0042"))
    assert out["merchantNormalized"] == "atm withdrawal 0042"
    assert out["descriptionRaw"] == "ATM WITHDRAWAL  0042"


def test_original_description_is_preferred_as_the_raw_description():
    out = norm(plaid_txn(original_description="SQ *BLUE BOTTLE 11/09"))
    assert out["descriptionRaw"] == "SQ *BLUE BOTTLE 11/09"
    assert out["merchantNormalized"] == "starbucks"  # merchant_name still wins for the merchant


def test_no_name_and_no_merchant_does_not_crash():
    out = norm(plaid_txn(merchant=None, name=None))
    assert out["merchantNormalized"] == ""
    assert out["descriptionRaw"] == ""


def test_pending_flag_and_link_to_the_pending_row_are_kept():
    pending = norm(plaid_txn("p1", pending=True))
    assert pending["pending"] is True
    assert "pendingTransactionId" not in pending
    posted = norm(plaid_txn("t2", pending_id="p1"))
    assert posted["pending"] is False
    assert posted["pendingTransactionId"] == "p1"


def test_provenance_tags_and_account_label():
    out = norm(plaid_txn())
    assert (out["source"], out["plaidEnv"], out["plaidItemId"]) == ("plaid", "sandbox", "item-1")
    assert out["accountId"] == "plaid-checking-0000"
    assert out["plaidAccountId"] == "acc-1"
    assert "balanceCents" not in out


def test_unknown_account_falls_back_to_the_plaid_account_id():
    out = normalize(plaid_txn(), account_labels={}, item_id="i", plaid_env="sandbox")
    assert out["accountId"] == "acc-1"


def test_raw_is_kept_with_floats_made_dynamo_safe():
    raw = norm(plaid_txn())["raw"]
    assert raw["location"]["lat"] == Decimal("40.7")
    assert isinstance(raw["amount"], Decimal)


@pytest.mark.parametrize("broken", [
    {"transaction_id": None}, {"transaction_id": ""}, {"date": None}, {"date": "11/10/2026x"},
    {"amount": None}, {"amount": "abc"},
])
def test_unusable_transactions_raise_value_error(broken):
    with pytest.raises(ValueError, match="transaction"):
        norm({**plaid_txn(), **broken})


def test_view_tolerates_a_row_with_no_balance():
    view = txn_view({**norm(plaid_txn(pending=True)), "categoryId": None})
    assert view["balanceCents"] is None
    assert view["pending"] is True
    assert view["source"] == "plaid"


# --- collect_updates ---------------------------------------------------------------------


class MutationError(Exception):
    pass


def is_mutation(err: Exception) -> bool:
    return isinstance(err, MutationError)


def test_pages_until_has_more_is_false_and_returns_the_last_cursor():
    pages = {
        "": {"added": [plaid_txn("a")], "next_cursor": "c1", "has_more": True, "request_id": "r1"},
        "c1": {"added": [plaid_txn("b")], "modified": [plaid_txn("a", amount=1)],
               "next_cursor": "c2", "has_more": True, "request_id": "r2"},
        "c2": {"removed": [{"transaction_id": "z"}], "next_cursor": "c3", "has_more": False,
               "request_id": "r3"},
    }
    calls: list[str] = []

    def fetch(cursor):
        calls.append(cursor)
        return pages[cursor]

    updates = collect_updates(fetch, "", is_mutation_error=is_mutation)
    assert calls == ["", "c1", "c2"]
    assert [t["transaction_id"] for t in updates.added] == ["a", "b"]
    assert len(updates.modified) == 1
    assert len(updates.removed) == 1
    assert updates.next_cursor == "c3"
    assert updates.pages == 3
    assert updates.request_ids == ["r1", "r2", "r3"]


def test_mutation_during_pagination_restarts_from_the_starting_cursor():
    calls: list[str] = []
    failed_once = []

    def fetch(cursor):
        calls.append(cursor)
        if cursor == "start":
            return {"added": [plaid_txn("stale" if not failed_once else "fresh")],
                    "next_cursor": "p2", "has_more": True}
        if not failed_once:
            failed_once.append(True)
            raise MutationError
        return {"added": [plaid_txn("b")], "next_cursor": "end", "has_more": False}

    updates = collect_updates(fetch, "start", is_mutation_error=is_mutation)
    # Restarted from "start", not from "p2" — and the first attempt's page was thrown away.
    assert calls == ["start", "p2", "start", "p2"]
    assert [t["transaction_id"] for t in updates.added] == ["fresh", "b"]
    assert updates.restarts == 1
    assert updates.next_cursor == "end"


def test_gives_up_after_too_many_restarts():
    def fetch(cursor):
        raise MutationError

    with pytest.raises(SyncRestartsExhaustedError):
        collect_updates(fetch, "c", is_mutation_error=is_mutation)


def test_restart_limit_is_finite():
    assert 1 <= MAX_RESTARTS <= 10


def test_other_errors_propagate_without_a_retry():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        collect_updates(fetch, "c", is_mutation_error=is_mutation)
    assert calls == ["c"]


def test_an_empty_first_sync_is_normal():
    updates = collect_updates(lambda c: {"next_cursor": "c1", "has_more": False}, "",
                              is_mutation_error=is_mutation)
    assert (updates.added, updates.modified, updates.removed) == ([], [], [])
    assert updates.next_cursor == "c1"


# --- plan --------------------------------------------------------------------------------


def test_plan_merges_posted_rows_before_any_removal():
    updates = Updates(
        # The removal of the pending ID arrives *before* the posted row that replaces it.
        removed=[{"transaction_id": "p1"}, {"transaction_id": "gone"}],
        added=[plaid_txn("new"), plaid_txn("posted", pending_id="p1")],
    )
    ops = plan(updates)
    assert [(o.kind, o.transaction_id or o.txn["transaction_id"]) for o in ops] == [
        (OP_UPSERT, "new"), (OP_MERGE, "p1"), (OP_REMOVE, "p1"), (OP_REMOVE, "gone"),
    ]
    assert ops[1].txn["transaction_id"] == "posted"


def test_plan_writes_each_transaction_once_with_its_latest_version():
    updates = Updates(added=[plaid_txn("a", amount=1.0)], modified=[plaid_txn("a", amount=2.0)])
    ops = plan(updates)
    assert len(ops) == 1
    assert ops[0].txn["amount"] == 2.0


def test_plan_drops_a_transaction_added_and_removed_in_the_same_sync():
    updates = Updates(added=[plaid_txn("a")], removed=[{"transaction_id": "a"}])
    assert [o.kind for o in plan(updates)] == [OP_REMOVE]


def test_a_still_pending_row_with_a_pending_id_is_not_a_merge():
    ops = plan(Updates(added=[plaid_txn("p2", pending=True, pending_id="p1")]))
    assert [o.kind for o in ops] == [OP_UPSERT]


# --- Item record -------------------------------------------------------------------------

ACCOUNT = {
    "account_id": "acc-1", "name": "Plaid Checking", "official_name": "Plaid Gold Checking",
    "mask": "0000", "type": "depository", "subtype": "checking",
    "balances": {"current": 110.0, "available": 100.5, "iso_currency_code": "USD"},
}


def test_account_view_has_a_readable_label_and_cached_balances_in_cents():
    view = account_view(ACCOUNT)
    assert view["accountId"] == "plaid-checking-0000"
    assert view["plaidAccountId"] == "acc-1"
    assert view["balanceCurrentCents"] == 11000
    assert view["balanceAvailableCents"] == 10050


def test_account_view_tolerates_missing_balances_and_names():
    view = account_view({"account_id": "acc-9"})
    assert view["balanceCurrentCents"] is None
    assert view["accountId"] == "acc-9"


def test_item_record_and_view_carry_no_token_and_the_view_no_cursor():
    record = new_plaid_item("item-1", institution_id="ins_109508",
                            institution_name="First Platypus Bank", accounts=[ACCOUNT],
                            plaid_env="sandbox", created_at="2026-11-15T00:00:00+00:00")
    assert record["cursor"] == ""
    assert not any("token" in key.lower() for key in record)
    view = plaid_item_view(record)
    assert "cursor" not in view
    assert view["accounts"][0]["mask"] == "0000"


# --- pending in the dashboard summary ------------------------------------------------------

CYCLE = {"cycleId": "M#2026-11"}
CATS = [{"categoryId": "food", "name": "Food", "sortOrder": 0, "status": "active"}]


def test_pending_counts_toward_spent_and_is_reported_separately():
    result = summarize(
        cycle=CYCLE, categories=CATS,
        budgets=[{"categoryId": "food", "amountCents": 10000}],
        transactions=[
            {"amountCents": -3000, "categoryId": "food"},
            {"amountCents": -1500, "categoryId": "food", "pending": True},
            {"amountCents": -700, "categoryId": None, "pending": True},
        ],
    )
    food = result["perCategory"][0]
    assert food["spentCents"] == 4500          # posted + pending
    assert food["pendingSpentCents"] == 1500   # ...of which this much is provisional
    assert food["remainingCents"] == 5500
    uncategorized = result["perCategory"][1]
    assert uncategorized["pendingSpentCents"] == 700
    assert result["totals"]["moneyOutCents"] == 5200
    assert result["totals"]["pendingSpentCents"] == 2200
    assert result["totals"]["pendingCount"] == 2


def test_no_pending_means_zero_pending_everywhere():
    result = summarize(cycle=CYCLE, categories=CATS, budgets=[],
                       transactions=[{"amountCents": -3000, "categoryId": "food"}])
    assert result["perCategory"][0]["pendingSpentCents"] == 0
    assert result["totals"]["pendingSpentCents"] == 0
    assert result["totals"]["pendingCount"] == 0
