"""The Plaid Sandbox purge's selection rule (owner decision 2026-11-15).

This is the one place deciding which of the owner's records get deleted, so the tests pin
what it must *never* select as hard as what it must.
"""
from __future__ import annotations

import pytest

from core.plaid_purge import PurgeBlockedError, plan_sandbox_purge


def _plaid_txn(txn_id, date="2026-09-01", env="sandbox", item="item-1"):
    return {"sk": f"TXN#{date}#{txn_id}", "txnId": txn_id, "date": date,
            "source": "plaid", "plaidEnv": env, "plaidItemId": item}


PARTITION = [
    {"sk": "PROFILE"},
    {"sk": "CAT#01GROC", "name": "Groceries"},
    {"sk": "BUDGET#M#2026-07#01GROC"},
    # The owner's real Chase CSV rows: no source attribute at all, or source=csv.
    {"sk": "TXN#2026-07-02#01CSV1", "txnId": "01CSV1", "date": "2026-07-02",
     "accountId": "chase-5980"},
    {"sk": "TXN#2026-07-03#01CSV2", "txnId": "01CSV2", "date": "2026-07-03", "source": "csv"},
    {"sk": "IMPORT#01CSVIMP", "source": "csv"},
    {"sk": "FILE#abc"},
    _plaid_txn("tx-a", "2026-08-21"),
    _plaid_txn("tx-b", "2026-11-15"),
    {"sk": "PLAIDTXN#tx-a", "date": "2026-08-21"},
    {"sk": "PLAIDTXN#tx-b", "date": "2026-11-15"},
    {"sk": "IMPORT#01SYNC1", "source": "plaid", "plaidItemId": "item-1"},
]


def test_selects_sandbox_rows_their_pointers_and_their_syncs_only():
    plan = plan_sandbox_purge(PARTITION)
    assert plan.transactions == ["TXN#2026-08-21#tx-a", "TXN#2026-11-15#tx-b"]
    assert plan.pointers == ["PLAIDTXN#tx-a", "PLAIDTXN#tx-b"]
    assert plan.imports == ["IMPORT#01SYNC1"]
    assert plan.left_alone == []
    assert plan.summary()["total"] == 5
    assert plan.summary()["dateRange"] == ["2026-08-21", "2026-11-15"]


def test_never_selects_csv_rows_settings_categories_or_budgets():
    selected = set(plan_sandbox_purge(PARTITION).keys)
    for item in PARTITION:
        if not item["sk"].startswith(("PLAIDTXN#", "IMPORT#01SYNC")) and \
                item.get("source") != "plaid":
            assert item["sk"] not in selected


def test_a_still_connected_item_blocks_the_whole_plan():
    with pytest.raises(PurgeBlockedError, match="disconnect"):
        plan_sandbox_purge([*PARTITION, {"sk": "PLAIDITEM#item-1"}])


def test_unproven_plaid_records_are_reported_not_deleted():
    plan = plan_sandbox_purge([
        _plaid_txn("tx-prod", env="production"),       # not Sandbox
        {"sk": "TXN#2026-09-02#tx-x", "txnId": "tx-x", "source": "plaid"},  # no env at all
        {"sk": "PLAIDTXN#tx-orphan"},                   # pointer with no Sandbox row
        {"sk": "IMPORT#01SYNC9", "source": "plaid", "plaidItemId": "item-other"},
    ])
    assert plan.keys == []
    assert sorted(plan.left_alone) == [
        "IMPORT#01SYNC9", "PLAIDTXN#tx-orphan", "TXN#2026-09-01#tx-prod", "TXN#2026-09-02#tx-x",
    ]


def test_empty_partition_plans_nothing():
    assert plan_sandbox_purge([]).summary()["total"] == 0
