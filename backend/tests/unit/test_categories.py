"""Unit tests for category domain logic + ULID generation (core/categories.py, core/ids.py)."""
from __future__ import annotations

import pytest

from core.categories import (
    MAX_NAME_LEN,
    STARTER_CATEGORIES,
    STATUS_ACTIVE,
    category_view,
    clean_name,
    new_category,
    starter_categories,
    validate_status,
)
from core.ids import new_ulid


# --- name validation -------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Groceries", "Groceries"),
        ("  Dining Out  ", "Dining Out"),
        ("Health\tCare", "Health Care"),  # collapse internal whitespace
        ("A" * MAX_NAME_LEN, "A" * MAX_NAME_LEN),  # exactly at the limit
    ],
)
def test_clean_name_normalizes(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_clean_name_rejects_empty(bad):
    with pytest.raises(ValueError, match="must not be empty"):
        clean_name(bad)


def test_clean_name_rejects_too_long():
    with pytest.raises(ValueError, match="at most"):
        clean_name("x" * (MAX_NAME_LEN + 1))


def test_clean_name_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        clean_name(None)  # type: ignore[arg-type]


# --- new_category ----------------------------------------------------------------------

def test_new_category_shape():
    cat = new_category("Coffee", sort_order=3, ulid="01JCOFFEE")
    assert cat == {
        "type": "CAT",
        "categoryId": "01JCOFFEE",
        "name": "Coffee",
        "status": STATUS_ACTIVE,
        "sortOrder": 3,
    }


def test_new_category_generates_ulid_when_absent():
    cat = new_category("Coffee", sort_order=0)
    assert len(cat["categoryId"]) == 26  # a real ULID


# --- starter set (FR-4.4) --------------------------------------------------------------

def test_starter_categories_are_ordered_and_active():
    starters = starter_categories()
    assert [c["name"] for c in starters] == list(STARTER_CATEGORIES)
    assert [c["sortOrder"] for c in starters] == list(range(len(STARTER_CATEGORIES)))
    assert all(c["status"] == STATUS_ACTIVE for c in starters)
    # Every starter gets a distinct ID.
    assert len({c["categoryId"] for c in starters}) == len(starters)


# --- status + view ---------------------------------------------------------------------

def test_validate_status_rejects_unknown():
    with pytest.raises(ValueError, match="status must be"):
        validate_status("deleted")


def test_category_view_drops_key_attributes():
    item = {
        "pk": "USER#s", "sk": "CAT#01J", "gsi1pk": "x",
        "categoryId": "01J", "name": "Coffee", "status": "active", "sortOrder": 2,
    }
    assert category_view(item) == {
        "categoryId": "01J", "name": "Coffee", "status": "active", "sortOrder": 2,
    }


# --- ULID ------------------------------------------------------------------------------

def test_ulid_is_26_chars_crockford():
    u = new_ulid()
    assert len(u) == 26
    assert all(ch in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for ch in u)


def test_ulid_is_time_sortable():
    early = new_ulid(now_ms=1_000_000_000_000, randomness=b"\x00" * 10)
    late = new_ulid(now_ms=2_000_000_000_000, randomness=b"\x00" * 10)
    assert early < late


def test_ulid_rejects_bad_randomness_length():
    with pytest.raises(ValueError, match="10 bytes"):
        new_ulid(randomness=b"\x00" * 9)
