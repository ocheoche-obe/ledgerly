"""CSV parsing & normalization (FR-2.1/2.3/2.4) — pure Python, no AWS imports.

Ingest is a *pluggable source abstraction* (FR-2.3): each bank/export format has a parser
registered under a format key, and callers select one (or let :func:`detect_format` sniff
the header). CSV is the first source; a live source (Plaid) can be added later behind the
same seam without touching the importer or anything downstream. This slice ships one parser:
Chase checking exports (the owner's bank).

A parser turns raw file text into two lists — normalized transactions and per-row errors —
and *never raises on a bad row* (FR-2.5): a malformed row is counted and reported, it does
not abort the file. Each normalized transaction keeps its original row under ``raw`` (FR-2.4)
alongside the normalized fields Ledgerly works with.

Dedupe (FR-2.2) rides on the transaction natural key computed here:
``txnId = sha256(accountId · date · amountCents · rawDescription · balanceCents)[:16]``
— balance is included per ADR-012 so legitimate same-day / same-amount / same-merchant
charges (three identical rideshare or subway fares on one day) are kept, not collapsed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

CHASE_CHECKING = "chase_checking"

# Chase checking export header (exact columns, in order).
_CHASE_HEADER = ["Details", "Posting Date", "Description", "Amount", "Type", "Balance"]

# A trailing " MM/DD" the bank appends to many card descriptions (the transaction date, as
# opposed to the posting date). Dropped from the normalized merchant; the real date comes
# from the Posting Date column.
_TRAILING_DATE = re.compile(r"\s\d{2}/\d{2}$")
# Control char (unit separator) joins natural-key parts — it cannot occur in CSV field text,
# so distinct rows can never collide through separator ambiguity.
_KEY_SEP = "\x1f"


def file_sha256(data: bytes) -> str:
    """SHA-256 of the raw uploaded bytes — the file-level idempotency key (AP 12, FR-2.2)."""
    return hashlib.sha256(data).hexdigest()


def _to_cents(value: str) -> int:
    """'-9.76' → -976, '744.00' → 74400. Decimal (not float) so cents are exact."""
    try:
        return int((Decimal(value.strip()) * 100).to_integral_value())
    except (InvalidOperation, AttributeError) as err:
        raise ValueError(f"invalid money value: {value!r}") from err


def normalize_merchant(description_raw: str) -> str:
    """A stable, lowercased merchant string from a raw bank description.

    Deliberately conservative this slice: collapse whitespace, drop a trailing " MM/DD"
    transaction date, lowercase. It does not yet strip processor prefixes, phone numbers, or
    store/location noise — that refinement rides with categorization + merchant rules
    (Slice 5/7), which is where merchant quality actually matters. It only needs to be
    deterministic here.
    """
    collapsed = " ".join(description_raw.split())
    return _TRAILING_DATE.sub("", collapsed).lower().strip()


def compute_txn_id(
    *, account_id: str, date: str, amount_cents: int, description_raw: str, balance_cents: int
) -> str:
    """Content-derived natural key (ADR-012). Equal keys ⇒ the same posted transaction."""
    parts = [account_id, date, str(amount_cents), description_raw, str(balance_cents)]
    return hashlib.sha256(_KEY_SEP.join(parts).encode("utf-8")).hexdigest()[:16]


def _normalize_chase_row(row: dict, *, account_id: str) -> dict:
    """One Chase row → a normalized transaction dict (no DynamoDB key attributes).

    Raises ValueError on any unusable field so the caller can count it as a failed row.
    """
    posting_date = (row.get("Posting Date") or "").strip()
    description_raw = (row.get("Description") or "").strip()
    amount = (row.get("Amount") or "").strip()
    balance = (row.get("Balance") or "").strip()

    if not posting_date or not description_raw or not amount or not balance:
        raise ValueError("missing required column (Posting Date/Description/Amount/Balance)")

    try:
        iso_date = datetime.strptime(posting_date, "%m/%d/%Y").date().isoformat()
    except ValueError as err:
        raise ValueError(f"invalid date: {posting_date!r} (expected MM/DD/YYYY)") from err

    amount_cents = _to_cents(amount)
    if amount_cents == 0:
        raise ValueError("amount is zero")
    balance_cents = _to_cents(balance)

    return {
        "type": "TXN",
        "txnId": compute_txn_id(
            account_id=account_id,
            date=iso_date,
            amount_cents=amount_cents,
            description_raw=description_raw,
            balance_cents=balance_cents,
        ),
        "date": iso_date,
        "amountCents": amount_cents,
        "direction": "credit" if amount_cents > 0 else "debit",
        "balanceCents": balance_cents,
        "accountId": account_id,
        "descriptionRaw": description_raw,
        "merchantNormalized": normalize_merchant(description_raw),
        "sourceType": (row.get("Type") or "").strip(),  # e.g. DEBIT_CARD, ACH_CREDIT
        # Keep only the real Chase columns (drops csv's restkey `None` bucket for the extra
        # trailing comma — DynamoDB can't store a None attribute name).
        "raw": {k: v for k, v in row.items() if k in _CHASE_HEADER},
    }


def _parse_chase(content: str, *, account_id: str) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    transactions: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()  # in-file dedupe (repeated identical rows within one export)

    # `line` is 1-based over data rows (header is line 0), matching how a human reads the file.
    for line, row in enumerate(reader, start=1):
        try:
            txn = _normalize_chase_row(row, account_id=account_id)
        except ValueError as err:
            errors.append({"line": line, "error": str(err), "raw": _row_snippet(row)})
            continue
        if txn["txnId"] in seen:
            # Genuinely identical to an earlier row in *this same file* → already accounted
            # for; count as a duplicate rather than emitting the same key twice.
            errors.append({"line": line, "error": "duplicate row in file", "raw": None})
            continue
        seen.add(txn["txnId"])
        transactions.append(txn)

    return {"transactions": transactions, "errors": errors}


def _row_snippet(row: dict) -> dict:
    """A compact, log-safe view of a bad row for the import report."""
    return {k: row.get(k) for k in ("Posting Date", "Description", "Amount") if row.get(k)}


# FR-2.3 — the source registry. Add a bank/format by registering its parser here.
_PARSERS = {CHASE_CHECKING: _parse_chase}
SUPPORTED_FORMATS = tuple(_PARSERS)


def detect_format(content: str) -> str | None:
    """Sniff the format from the header row, or None if unrecognized."""
    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    header = [h.strip() for h in first_line.split(",")]
    if header[: len(_CHASE_HEADER)] == _CHASE_HEADER:
        return CHASE_CHECKING
    return None


def parse(content: str, *, account_id: str, format_key: str | None = None) -> dict:
    """Parse raw CSV text into ``{"transactions": [...], "errors": [...]}`` (FR-2.5).

    ``format_key`` selects a registered parser; if omitted it is detected from the header.
    Raises ValueError only for a *file-level* problem (unknown/undetectable format) — never
    for a bad row.
    """
    key = format_key or detect_format(content)
    if key is None:
        raise ValueError("unrecognized CSV format (no matching parser)")
    if key not in _PARSERS:
        raise ValueError(f"unsupported format: {key!r}")
    return _PARSERS[key](content, account_id=account_id)
