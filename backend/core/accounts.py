"""Account identity helpers (ADR-013) — pure Python, no AWS imports.

A bank CSV's rows don't name the account they came from; the owner asserts it at upload
time as a free-text ``accountLabel`` (pre-filled in the UI from the filename, editable).
Ledgerly derives a stable ``accountId`` from that label — and ``accountId`` is part of the
transaction natural key (ADR-012, architecture §2.4), so it *must* be deterministic and
consistent across every export of the same account. That determinism lives here, in core,
where it is unit-tested; the API layer normalizes whatever label the client sends.
"""
from __future__ import annotations

import re

MAX_LABEL_LEN = 60

# Normalization for the key component: lowercase, keep alphanumerics, everything else → a
# single hyphen, trimmed. "Chase ...5980" → "chase-5980"; stable and URL/key-safe.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def clean_account_label(label: str) -> str:
    """Validate + tidy the owner-facing account label. Raises ValueError if unusable."""
    if not isinstance(label, str):
        raise ValueError("account label must be a string")
    cleaned = " ".join(label.split())  # trim + collapse internal whitespace
    if not cleaned:
        raise ValueError("account label must not be empty")
    if len(cleaned) > MAX_LABEL_LEN:
        raise ValueError(f"account label must be at most {MAX_LABEL_LEN} characters")
    return cleaned


def normalize_account_id(label: str) -> str:
    """The dedupe-key component derived from a label. Deterministic (ADR-012/013).

    Runs :func:`clean_account_label` first so an invalid label can never yield a key.
    """
    cleaned = clean_account_label(label)
    account_id = _NON_ALNUM.sub("-", cleaned.lower()).strip("-")
    if not account_id:  # label was e.g. all punctuation
        raise ValueError("account label must contain at least one letter or digit")
    return account_id
