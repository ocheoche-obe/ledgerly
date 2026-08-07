"""Budget domain logic + dashboard aggregation (FR-4.3, FR-5.1) — pure Python, no AWS imports.

Two jobs, both AWS-free so they are unit-testable in isolation (architecture §5.2):

1. **The budget item.** A budget is an amount for one category in one cycle, keyed
   ``BUDGET#<cycleId>#<categoryId>`` — cycle-major so a single Query gets a whole cycle
   (architecture §2.4, AP 4). A budget exists only when the owner sets an amount; a category
   with no budget for a cycle simply shows actuals with no target (§2.3).

2. **The aggregation** (``summarize``). Budgets + the cycle's transactions → the dashboard's
   per-category rows and totals. This is the whole of architecture §3.3's "aggregate per
   category + totals" step, kept out of the Lambda so the arithmetic — which is what the owner
   actually reads and trusts — is testable without any AWS at all.

**Sign conventions**, since this is where money changes meaning. Stored ``amountCents`` is
signed (negative = money out, per ``csv_normalize``). The dashboard talks in *spend*, so a row's
``spentCents`` is the **negated net** of its transactions: a $50 grocery charge is +5000 spent,
and a $10 refund in the same category nets it down to +4000. That makes refunds behave the way
an owner expects rather than inflating both sides. A category with net inflow (Income) reports
negative spend — the UI renders those as income rather than as a budget bar.
"""
from __future__ import annotations

# A budget amount is a non-negative whole number of cents. The ceiling is a sanity guard
# against a fat-fingered entry (a $10M monthly grocery budget is a typo, not a plan).
MAX_AMOUNT_CENTS = 1_000_000_000  # $10,000,000.00

UNCATEGORIZED_ROW_ID = "__uncategorized__"
UNCATEGORIZED_ROW_NAME = "Uncategorized"


def budget_sk(cycle_id: str, category_id: str) -> str:
    """Sort key ``BUDGET#<cycleId>#<categoryId>`` (architecture §2.4).

    Note the cycle ID itself contains a ``#`` (``M#2026-07``), so the key reads
    ``BUDGET#M#2026-07#<catId>`` and the whole-cycle query prefix is ``BUDGET#<cycleId>#``.
    """
    return f"BUDGET#{cycle_id}#{category_id}"


def budget_prefix(cycle_id: str) -> str:
    """The ``begins_with`` prefix that selects exactly one cycle's budgets (AP 4)."""
    return f"BUDGET#{cycle_id}#"


def validate_amount_cents(value) -> int:
    """Validate an owner-supplied budget amount. Raises ValueError on anything unusable."""
    if isinstance(value, bool) or not isinstance(value, int):
        # bool is an int subclass in Python; True would otherwise sail through as 1 cent.
        raise ValueError("amountCents must be a whole number of cents")
    if value < 0:
        raise ValueError("amountCents must not be negative")
    if value > MAX_AMOUNT_CENTS:
        raise ValueError(f"amountCents must be at most {MAX_AMOUNT_CENTS}")
    return value


def new_budget(cycle_id: str, category_id: str, amount_cents: int) -> dict:
    """A budget item body (sans key attributes, which the adapter adds)."""
    return {
        "type": "BUDGET",
        "cycleId": cycle_id,
        "categoryId": category_id,
        "amountCents": validate_amount_cents(amount_cents),
    }


def budget_view(item: dict) -> dict:
    """Owner-facing projection — drops key attributes, coerces DynamoDB Decimals to int."""
    return {
        "cycleId": item["cycleId"],
        "categoryId": item["categoryId"],
        "amountCents": int(item["amountCents"]),
    }


def summarize(
    *,
    cycle: dict,
    categories: list[dict],
    budgets: list[dict],
    transactions: list[dict],
) -> dict:
    """Budgets + a cycle's transactions → the dashboard payload (FR-5.1, architecture §3.3).

    Returns ``{cycle, perCategory: [...], totals: {...}}``.

    A row appears for every **active** category (so a budget the owner set is always visible,
    even at zero spend), plus archived categories that still have activity or a budget in this
    cycle — history is never hidden (FR-4.5's spirit) — plus a synthetic *Uncategorized* row
    whenever transactions have no category. That last row matters: without it, money the
    pipeline hasn't filed silently vanishes from a screen whose entire job is "where did my
    money go", and the totals would not reconcile against the bank.

    Rows are ordered by the categories' ``sortOrder``, with Uncategorized last.
    """
    budget_by_cat = {b["categoryId"]: int(b["amountCents"]) for b in budgets}

    net_by_cat: dict[str | None, int] = {}
    count_by_cat: dict[str | None, int] = {}
    money_in = money_out = 0
    for txn in transactions:
        amount = int(txn["amountCents"])
        cat_id = txn.get("categoryId")  # None → the Uncategorized row
        net_by_cat[cat_id] = net_by_cat.get(cat_id, 0) + amount
        count_by_cat[cat_id] = count_by_cat.get(cat_id, 0) + 1
        if amount >= 0:
            money_in += amount
        else:
            money_out -= amount

    rows: list[dict] = []
    for category in sorted(categories, key=lambda c: (c.get("sortOrder", 0), c["name"])):
        cat_id = category["categoryId"]
        active = category.get("status", "active") == "active"
        has_budget = cat_id in budget_by_cat
        has_activity = cat_id in net_by_cat
        if not (active or has_budget or has_activity):
            continue  # archived, unused this cycle → nothing to say about it
        rows.append(_row(
            category_id=cat_id,
            name=category["name"],
            budget_cents=budget_by_cat.get(cat_id),
            net_cents=net_by_cat.get(cat_id, 0),
            count=count_by_cat.get(cat_id, 0),
            archived=not active,
        ))

    if None in net_by_cat:
        rows.append(_row(
            category_id=UNCATEGORIZED_ROW_ID,
            name=UNCATEGORIZED_ROW_NAME,
            budget_cents=None,
            net_cents=net_by_cat[None],
            count=count_by_cat[None],
            archived=False,
        ))

    budgeted = sum(budget_by_cat.values())
    # "Remaining" only counts categories the owner actually budgeted — spend in an unbudgeted
    # category isn't over-spend against a plan that was never made.
    spent_against_budget = sum(r["spentCents"] for r in rows if r["budgetCents"] is not None)
    return {
        "cycle": cycle,
        "perCategory": rows,
        "totals": {
            "moneyInCents": money_in,
            "moneyOutCents": money_out,
            "netCents": money_in - money_out,
            "budgetedCents": budgeted,
            "spentAgainstBudgetCents": spent_against_budget,
            "remainingCents": budgeted - spent_against_budget,
            "transactionCount": len(transactions),
            "uncategorizedCount": count_by_cat.get(None, 0),
        },
    }


def _row(
    *,
    category_id: str,
    name: str,
    budget_cents: int | None,
    net_cents: int,
    count: int,
    archived: bool,
) -> dict:
    spent = -net_cents  # money out is positive spend; refunds net it down
    return {
        "categoryId": category_id,
        "name": name,
        "budgetCents": budget_cents,
        "spentCents": spent,
        "netCents": net_cents,
        "transactionCount": count,
        "remainingCents": None if budget_cents is None else budget_cents - spent,
        "over": budget_cents is not None and spent > budget_cents,
        "archived": archived,
    }
