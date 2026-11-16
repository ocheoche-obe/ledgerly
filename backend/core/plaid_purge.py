"""Which records a Plaid Sandbox purge deletes — pure, no AWS imports.

Owner decision 2026-11-15: Sandbox data moves to its own Cognito user, and the Sandbox rows
already written under the owner's partition are deleted. This module only *plans* that
delete from a list of the partition's items, so the selection rule is unit-tested and the
script that executes it (``ops/purge_plaid_sandbox.py``) stays a thin loop.

The selection is deliberately narrow. Anything that does not prove it is Sandbox Plaid data
is left alone and *reported*, never deleted:

* ``TXN#`` rows with ``source == "plaid"`` **and** ``plaidEnv == "sandbox"``.
* ``PLAIDTXN#<id>`` pointers whose transaction is one of those rows (a pointer carries no
  provenance of its own; its ``<id>`` is the row's ``txnId``).
* ``IMPORT#`` records with ``source == "plaid"`` whose ``plaidItemId`` is an Item those rows
  came from.

A ``PLAIDITEM#`` record still present blocks the plan: the connection must be disconnected
through the app first, which also revokes it at Plaid and deletes its access token.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SANDBOX = "sandbox"
PLAID = "plaid"


class PurgeBlockedError(Exception):
    """The partition is not in a state where the purge is safe to run."""


@dataclass
class PurgePlan:
    transactions: list[str] = field(default_factory=list)  # sort keys
    pointers: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    # Reported, not deleted — Plaid-looking records the rule above could not prove are Sandbox.
    left_alone: list[str] = field(default_factory=list)
    item_ids: set[str] = field(default_factory=set)
    date_range: tuple[str, str] | None = None

    @property
    def keys(self) -> list[str]:
        return [*self.transactions, *self.pointers, *self.imports]

    def summary(self) -> dict:
        return {
            "transactions": len(self.transactions),
            "pointers": len(self.pointers),
            "imports": len(self.imports),
            "total": len(self.keys),
            "leftAlone": len(self.left_alone),
            "plaidItemIds": sorted(self.item_ids),
            "dateRange": list(self.date_range) if self.date_range else None,
        }


def plan_sandbox_purge(items: list[dict]) -> PurgePlan:
    """One partition's items (every ``sk``) → the plan. Raises PurgeBlockedError if an Item
    is still connected."""
    connected = [i["sk"] for i in items if i["sk"].startswith("PLAIDITEM#")]
    if connected:
        raise PurgeBlockedError(
            f"{len(connected)} Plaid connection(s) still linked ({', '.join(connected)}); "
            "disconnect them in the app first so Plaid revokes the Item and the token is deleted"
        )

    plan = PurgePlan()
    sandbox_txn_ids: set[str] = set()
    dates: list[str] = []
    for item in items:
        sk = item["sk"]
        if not sk.startswith("TXN#"):
            continue
        if item.get("source") == PLAID and item.get("plaidEnv") == SANDBOX:
            plan.transactions.append(sk)
            sandbox_txn_ids.add(item["txnId"])
            dates.append(item["date"])
            if item.get("plaidItemId"):
                plan.item_ids.add(item["plaidItemId"])
        elif item.get("source") == PLAID:
            plan.left_alone.append(sk)  # Plaid, but not provably Sandbox

    for item in items:
        sk = item["sk"]
        if sk.startswith("PLAIDTXN#"):
            if sk.removeprefix("PLAIDTXN#") in sandbox_txn_ids:
                plan.pointers.append(sk)
            else:
                plan.left_alone.append(sk)
        elif sk.startswith("IMPORT#") and item.get("source") == PLAID:
            if item.get("plaidItemId") in plan.item_ids:
                plan.imports.append(sk)
            else:
                plan.left_alone.append(sk)

    if dates:
        plan.date_range = (min(dates), max(dates))
    return plan
