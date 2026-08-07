"""Unit tests for `core/budgets` — the budget item and the dashboard aggregation (FR-5.1).

Pure, no AWS. This is the arithmetic the owner reads off the dashboard and trusts, so the
sign conventions (spend vs. income vs. refunds), the "remaining" definition, and the
uncategorized row all get pinned down here rather than discovered in the browser.
"""
from __future__ import annotations

import pytest

from core.budgets import (
    MAX_AMOUNT_CENTS,
    UNCATEGORIZED_ROW_ID,
    budget_prefix,
    budget_sk,
    budget_view,
    new_budget,
    summarize,
    validate_amount_cents,
)

CYCLE = {"cycleId": "M#2026-07", "kind": "monthly", "start": "2026-07-01", "end": "2026-07-31"}
GROC = "01CATGROC"
DINE = "01CATDINE"
INCOME = "01CATINC"

CATEGORIES = [
    {"categoryId": INCOME, "name": "Income", "status": "active", "sortOrder": 0},
    {"categoryId": GROC, "name": "Groceries", "status": "active", "sortOrder": 1},
    {"categoryId": DINE, "name": "Dining Out", "status": "active", "sortOrder": 2},
]


def _txn(amount_cents: int, category_id: str | None = None) -> dict:
    return {"txnId": f"t{amount_cents}{category_id}", "date": "2026-07-05",
            "amountCents": amount_cents, "categoryId": category_id}


def _rows(result: dict) -> dict[str, dict]:
    return {r["categoryId"]: r for r in result["perCategory"]}


# --- keys & validation ------------------------------------------------------------------

def test_budget_key_is_cycle_major():
    # Cycle-major so one begins_with Query gets a whole cycle (AP 4); note the cycle ID's own
    # '#' means the key has three segments, and the prefix must include the trailing '#'.
    assert budget_sk("M#2026-07", GROC) == "BUDGET#M#2026-07#01CATGROC"
    assert budget_prefix("M#2026-07") == "BUDGET#M#2026-07#"
    assert budget_sk("M#2026-07", GROC).startswith(budget_prefix("M#2026-07"))


def test_budget_prefix_does_not_match_a_neighbouring_cycle():
    assert not budget_sk("M#2026-07", GROC).startswith(budget_prefix("M#2026-0"))


@pytest.mark.parametrize("bad", [-1, "400", 4.5, None, True, MAX_AMOUNT_CENTS + 1])
def test_validate_amount_rejects_unusable_values(bad):
    with pytest.raises(ValueError):
        validate_amount_cents(bad)


def test_validate_amount_accepts_zero_and_the_ceiling():
    # Zero is a legitimate target ("spend nothing here this cycle"), distinct from no budget.
    assert validate_amount_cents(0) == 0
    assert validate_amount_cents(MAX_AMOUNT_CENTS) == MAX_AMOUNT_CENTS


def test_new_budget_and_view_round_trip():
    item = new_budget("M#2026-07", GROC, 40000)
    assert item == {"type": "BUDGET", "cycleId": "M#2026-07",
                    "categoryId": GROC, "amountCents": 40000}
    assert budget_view(item)["amountCents"] == 40000


# --- aggregation ------------------------------------------------------------------------

def test_spend_is_the_negated_net_so_debits_read_positive():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES,
        budgets=[{"categoryId": GROC, "amountCents": 40000}],
        transactions=[_txn(-5000, GROC), _txn(-2500, GROC)],
    )
    row = _rows(result)[GROC]
    assert row["spentCents"] == 7500
    assert row["budgetCents"] == 40000
    assert row["remainingCents"] == 32500
    assert row["over"] is False
    assert row["transactionCount"] == 2


def test_a_refund_reduces_spend_rather_than_inflating_both_sides():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES, budgets=[],
        transactions=[_txn(-5000, GROC), _txn(1000, GROC)],  # $50 charge, $10 returned
    )
    assert _rows(result)[GROC]["spentCents"] == 4000


def test_over_budget_is_flagged_and_remaining_goes_negative():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES,
        budgets=[{"categoryId": DINE, "amountCents": 10000}],
        transactions=[_txn(-12500, DINE)],
    )
    row = _rows(result)[DINE]
    assert row["over"] is True
    assert row["remainingCents"] == -2500


def test_spending_exactly_the_budget_is_not_over():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES,
        budgets=[{"categoryId": DINE, "amountCents": 10000}],
        transactions=[_txn(-10000, DINE)],
    )
    assert _rows(result)[DINE]["over"] is False
    assert _rows(result)[DINE]["remainingCents"] == 0


def test_income_reports_negative_spend_and_lands_in_money_in():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES, budgets=[],
        transactions=[_txn(250000, INCOME), _txn(-5000, GROC)],
    )
    assert _rows(result)[INCOME]["spentCents"] == -250000
    assert result["totals"]["moneyInCents"] == 250000
    assert result["totals"]["moneyOutCents"] == 5000
    assert result["totals"]["netCents"] == 245000


def test_uncategorized_transactions_get_their_own_row():
    # Without this row, money the pipeline hasn't filed would vanish from the one screen whose
    # job is "where did my money go" — and the totals would not reconcile against the bank.
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES, budgets=[],
        transactions=[_txn(-5000, GROC), _txn(-1234, None), _txn(-766, None)],
    )
    row = _rows(result)[UNCATEGORIZED_ROW_ID]
    assert row["spentCents"] == 2000
    assert row["transactionCount"] == 2
    assert row["budgetCents"] is None
    assert result["perCategory"][-1]["categoryId"] == UNCATEGORIZED_ROW_ID  # always last
    assert result["totals"]["uncategorizedCount"] == 2


def test_no_uncategorized_row_when_everything_is_categorized():
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES, budgets=[], transactions=[_txn(-5000, GROC)],
    )
    assert UNCATEGORIZED_ROW_ID not in _rows(result)


def test_every_active_category_appears_even_with_no_activity():
    result = summarize(cycle=CYCLE, categories=CATEGORIES, budgets=[], transactions=[])
    assert list(_rows(result)) == [INCOME, GROC, DINE]  # sortOrder preserved
    assert all(r["spentCents"] == 0 for r in result["perCategory"])


def test_archived_category_is_hidden_unless_it_has_history_or_a_budget():
    archived = [*CATEGORIES, {"categoryId": "01OLD", "name": "Old", "status": "archived",
                              "sortOrder": 9}]
    quiet = summarize(cycle=CYCLE, categories=archived, budgets=[], transactions=[])
    assert "01OLD" not in _rows(quiet)

    with_history = summarize(
        cycle=CYCLE, categories=archived, budgets=[], transactions=[_txn(-999, "01OLD")],
    )
    assert _rows(with_history)["01OLD"]["archived"] is True


def test_remaining_counts_only_budgeted_categories():
    # Spend in a category with no budget isn't over-spend against a plan that was never made,
    # so it must not eat into "remaining".
    result = summarize(
        cycle=CYCLE, categories=CATEGORIES,
        budgets=[{"categoryId": GROC, "amountCents": 40000}],
        transactions=[_txn(-10000, GROC), _txn(-30000, DINE), _txn(-5000, None)],
    )
    totals = result["totals"]
    assert totals["budgetedCents"] == 40000
    assert totals["spentAgainstBudgetCents"] == 10000
    assert totals["remainingCents"] == 30000
    assert totals["moneyOutCents"] == 45000  # every debit still shows in money out
    assert totals["transactionCount"] == 3


def test_empty_cycle_produces_zero_totals_not_an_error():
    result = summarize(cycle=CYCLE, categories=CATEGORIES, budgets=[], transactions=[])
    assert result["totals"] == {
        "moneyInCents": 0, "moneyOutCents": 0, "netCents": 0, "budgetedCents": 0,
        "spentAgainstBudgetCents": 0, "remainingCents": 0,
        "transactionCount": 0, "uncategorizedCount": 0,
    }
    assert result["cycle"] == CYCLE
