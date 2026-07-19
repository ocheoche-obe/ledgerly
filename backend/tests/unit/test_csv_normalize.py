"""Unit tests for CSV parsing & normalization (core/csv_normalize.py).

All CSV text here is synthetic Chase-format data (no real transactions) — it reproduces the
*shapes* that matter: signed amounts, quoted descriptions, trailing embedded dates, and the
same-day/same-amount/same-merchant collisions that ADR-012's balance-in-key handles.
"""
from __future__ import annotations

import pytest

from core.csv_normalize import (
    CHASE_CHECKING,
    compute_txn_id,
    detect_format,
    file_sha256,
    normalize_merchant,
    parse,
)

HEADER = "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #"


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


# --- money + field normalization -------------------------------------------------------

def test_basic_debit_and_credit_row():
    content = _csv(
        'DEBIT,07/03/2026,"BLANK STREET COFFEE NY          07/03",-6.75,DEBIT_CARD,1232.56,,',
        'CREDIT,07/03/2026,"Payroll deposit",744.00,ACH_CREDIT,1976.56,,',
    )
    result = parse(content, account_id="chase-5980")
    assert result["errors"] == []
    debit, credit = result["transactions"]

    assert debit["date"] == "2026-07-03"
    assert debit["amountCents"] == -675
    assert debit["direction"] == "debit"
    assert debit["balanceCents"] == 123256
    assert debit["merchantNormalized"] == "blank street coffee ny"  # trailing date dropped
    assert debit["sourceType"] == "DEBIT_CARD"
    assert debit["accountId"] == "chase-5980"
    assert len(debit["txnId"]) == 16
    # Raw row preserved (FR-2.4).
    assert debit["raw"]["Amount"] == "-6.75"

    assert credit["amountCents"] == 74400
    assert credit["direction"] == "credit"


def test_decimal_money_is_exact_no_float_drift():
    # 0.1 + 0.2 style values that float would mangle.
    content = _csv('DEBIT,07/01/2026,"X",-11.10,DEBIT_CARD,20.30,,')
    txn = parse(content, account_id="a")["transactions"][0]
    assert txn["amountCents"] == -1110
    assert txn["balanceCents"] == 2030


# --- the ADR-012 case: same-day / same-amount / same-merchant, distinct by balance -----

def test_identical_same_day_charges_are_all_kept():
    content = _csv(
        'DEBIT,06/29/2026,"MIRRA VR BELLEVUE WA         06/29",-31.76,DEBIT_CARD,3285.11,,',
        'DEBIT,06/29/2026,"MIRRA VR BELLEVUE WA         06/29",-31.76,DEBIT_CARD,3316.87,,',
        'DEBIT,06/29/2026,"MIRRA VR BELLEVUE WA         06/29",-31.76,DEBIT_CARD,3348.63,,',
    )
    result = parse(content, account_id="chase-5980")
    assert len(result["transactions"]) == 3  # not collapsed to 1
    assert len({t["txnId"] for t in result["transactions"]}) == 3  # distinct keys
    assert result["errors"] == []


def test_truly_identical_row_within_file_is_a_duplicate():
    # Same everything *including balance* → same posted txn appearing twice in one file.
    row = 'DEBIT,07/06/2026,"MTA PAYGO NY   07/03",-3.00,DEBIT_CARD,1179.52,,'
    result = parse(_csv(row, row), account_id="a")
    assert len(result["transactions"]) == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["error"] == "duplicate row in file"


# --- malformed rows are counted, never fatal (FR-2.5) ----------------------------------

def test_bad_date_is_counted_not_fatal():
    content = _csv(
        'DEBIT,99/99/2026,"BROKEN",-5.00,DEBIT_CARD,10.00,,',
        'DEBIT,07/01/2026,"GOOD",-5.00,DEBIT_CARD,5.00,,',
    )
    result = parse(content, account_id="a")
    assert len(result["transactions"]) == 1  # the good row survived
    assert len(result["errors"]) == 1
    assert "invalid date" in result["errors"][0]["error"]
    assert result["errors"][0]["line"] == 1


def test_bad_amount_is_counted():
    content = _csv('DEBIT,07/01/2026,"X",not-a-number,DEBIT_CARD,10.00,,')
    result = parse(content, account_id="a")
    assert result["transactions"] == []
    assert "invalid money value" in result["errors"][0]["error"]


def test_missing_required_field_is_counted():
    content = _csv('DEBIT,07/01/2026,"X",,DEBIT_CARD,10.00,,')  # empty Amount
    result = parse(content, account_id="a")
    assert "missing required column" in result["errors"][0]["error"]


def test_zero_amount_is_rejected():
    content = _csv('DEBIT,07/01/2026,"X",0.00,DEBIT_CARD,10.00,,')
    result = parse(content, account_id="a")
    assert result["transactions"] == []
    assert "amount is zero" in result["errors"][0]["error"]


def test_quoted_description_with_comma_is_preserved():
    content = _csv('CREDIT,06/30/2026,"Goldman Sachs, transfer",400.00,ACH_CREDIT,900.00,,')
    txn = parse(content, account_id="a")["transactions"][0]
    assert txn["descriptionRaw"] == "Goldman Sachs, transfer"


# --- txnId natural key (ADR-012) -------------------------------------------------------

def test_compute_txn_id_is_deterministic():
    kwargs = dict(account_id="a", date="2026-07-03", amount_cents=-675,
                  description_raw="COFFEE", balance_cents=123256)
    assert compute_txn_id(**kwargs) == compute_txn_id(**kwargs)


def test_balance_changes_the_txn_id():
    base = dict(account_id="a", date="2026-07-03", amount_cents=-3176, description_raw="MIRRA")
    assert compute_txn_id(**base, balance_cents=328511) != compute_txn_id(**base, balance_cents=331687)


def test_account_id_changes_the_txn_id():
    base = dict(date="2026-07-03", amount_cents=-675, description_raw="X", balance_cents=100)
    assert compute_txn_id(account_id="a", **base) != compute_txn_id(account_id="b", **base)


# --- merchant normalization ------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("BLANK STREET COFFEE NY          07/03", "blank street coffee ny"),
        ("  Trader  Joe's   #13  ", "trader joe's #13"),
        ("SPOTIFY USA 877-7781161 NY  06/30", "spotify usa 877-7781161 ny"),
    ],
)
def test_normalize_merchant(raw, expected):
    assert normalize_merchant(raw) == expected


# --- format detection + registry (FR-2.3) ----------------------------------------------

def test_detect_format_recognizes_chase():
    assert detect_format(_csv()) == CHASE_CHECKING


def test_detect_format_returns_none_for_unknown():
    assert detect_format("foo,bar,baz\n1,2,3\n") is None


def test_parse_raises_on_unrecognized_format():
    with pytest.raises(ValueError, match="unrecognized CSV format"):
        parse("foo,bar\n1,2\n", account_id="a")


def test_parse_raises_on_unsupported_explicit_format():
    with pytest.raises(ValueError, match="unsupported format"):
        parse(_csv(), account_id="a", format_key="wells_fargo")


# --- file hash (FR-2.2 file-level idempotency) -----------------------------------------

def test_file_sha256_is_stable_and_content_sensitive():
    a = b"Details,Posting Date\nDEBIT,07/01/2026\n"
    assert file_sha256(a) == file_sha256(a)
    assert file_sha256(a) != file_sha256(a + b"x")
