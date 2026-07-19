"""Category domain logic (FR-4.1, FR-4.4) — pure Python, no AWS imports.

A category is an owner-defined spending bucket. This module owns the *shape* and *rules* of
a category (validation, the new-category item, the owner-facing projection, the starter
set); persistence lives in ``adapters/`` (architecture §5.2). Categories key as
``CAT#<ulid>`` (architecture §2.4); the ULID sorts by creation time, and ``sortOrder`` lets
the owner reorder later.
"""
from __future__ import annotations

from core.ids import new_ulid

MAX_NAME_LEN = 60
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
_VALID_STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED)

# FR-4.4 — a sensible starter set offered at first run, fully editable. Order here is the
# initial sortOrder. Kept deliberately generic (US personal-budget shape); the owner adds,
# renames, and archives freely via CRUD.
STARTER_CATEGORIES = (
    "Income",
    "Housing",
    "Utilities",
    "Groceries",
    "Dining Out",
    "Transportation",
    "Health",
    "Insurance",
    "Shopping",
    "Entertainment",
    "Subscriptions",
    "Savings & Investments",
    "Debt Payments",
    "Miscellaneous",
)


def clean_name(name: str) -> str:
    """Validate + normalize a category name. Raises ValueError on anything unusable."""
    if not isinstance(name, str):
        raise ValueError("category name must be a string")
    cleaned = " ".join(name.split())  # trim + collapse internal whitespace
    if not cleaned:
        raise ValueError("category name must not be empty")
    if len(cleaned) > MAX_NAME_LEN:
        raise ValueError(f"category name must be at most {MAX_NAME_LEN} characters")
    return cleaned


def new_category(name: str, *, sort_order: int, ulid: str | None = None) -> dict:
    """A brand-new category item (sans key attributes, which the adapter adds).

    `ulid` is injectable so persistence/tests stay deterministic; production passes None and
    a time-sortable ULID is generated.
    """
    cat_id = ulid or new_ulid()
    return {
        "type": "CAT",
        "categoryId": cat_id,
        "name": clean_name(name),
        "status": STATUS_ACTIVE,
        "sortOrder": sort_order,
    }


def starter_categories() -> list[dict]:
    """The full starter set as new-category items, in display order (FR-4.4)."""
    return [new_category(name, sort_order=i) for i, name in enumerate(STARTER_CATEGORIES)]


def validate_status(status: str) -> str:
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {_VALID_STATUSES}")
    return status


def category_view(item: dict) -> dict:
    """Owner-facing projection — drops DynamoDB key attributes (pk/sk/gsi*)."""
    return {
        "categoryId": item["categoryId"],
        "name": item["name"],
        "status": item.get("status", STATUS_ACTIVE),
        # Coerce to int: DynamoDB returns numbers as Decimal, which won't JSON-serialize.
        "sortOrder": int(item.get("sortOrder", 0)),
    }
