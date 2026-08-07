"""/cycles — the dashboard read and the budget write (FR-4.3, FR-5.1–5.3).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3); the cycle
math lives in `core/cycles.py`, the aggregation in `core/budgets.py`, persistence in `adapters/`.

Routes (authorized by the API Gateway JWT authorizer):
  GET /cycles                                   → cycles for the picker, newest first (AP 15)
  GET /cycles/{cycleRef}/summary                → budget vs actual + totals (AP 4+6, §3.3)
  PUT /cycles/{cycleRef}/budgets/{categoryId}   → {amountCents} set, {amountCents: null} clear

**`cycleRef` is `current` or any ISO date inside the cycle** — not the raw cycle ID. Cycle IDs
contain a `#` (`M#2026-07`), which has to be percent-encoded to survive a URL, and a client that
got the encoding wrong would silently address a *different* (nonexistent) cycle: budgets written
under a bogus ID would persist and never be read back. Resolving a date through the cadence
history instead means the server derives the canonical ID, so an unroutable cycle simply cannot
be addressed. Every response echoes the resolved `cycle` object, so the SPA never derives IDs.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from adapters.dynamo import (
    TXN_QUERY_LIMIT,
    delete_budget,
    first_transaction_date,
    get_or_create_settings,
    list_budgets,
    list_categories,
    put_budget,
    query_transactions,
)
from core.budgets import summarize
from core.cycles import cycle_for, recent_cycles, today_utc

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENT = "current"


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/cycles", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    method = _method(event)
    params = event.get("pathParameters") or {}
    try:
        if method == "GET" and not params.get("cycleRef"):
            return _list_cycles(sub)
        if method == "GET":
            return _summary(sub, params["cycleRef"])
        if method == "PUT" and params.get("categoryId"):
            return _set_budget(sub, params["cycleRef"], params["categoryId"], _parse_body(event))
    except ValueError as err:
        logger.info(json.dumps({"route": f"{method} /cycles", "sub": sub, "err": str(err)}))
        return _response(400, {"message": str(err)})

    return _response(405, {"message": "Method not allowed"})


def _list_cycles(sub: str) -> dict:
    """AP 15 — the picker's list (FR-5.3). Bounded by the owner's first transaction, so it
    never offers cycles that predate any data."""
    settings = get_or_create_settings(sub)
    earliest = first_transaction_date(sub)
    cycles = recent_cycles(
        settings["cadences"],
        today=today_utc(),
        earliest=date.fromisoformat(earliest) if earliest else None,
    )
    return _response(200, {
        "cycles": [c.as_view() for c in cycles],
        "currentCycleId": cycles[0].cycle_id,
    })


def _summary(sub: str, cycle_ref: str) -> dict:
    """Architecture §3.3 — resolve the window, read budgets + transactions, aggregate."""
    settings = get_or_create_settings(sub)
    cycle = _resolve_cycle(settings["cadences"], cycle_ref)

    budgets = list_budgets(sub, cycle.cycle_id)
    txns = query_transactions(
        sub, date_from=cycle.start.isoformat(), date_to=cycle.end.isoformat(),
        limit=TXN_QUERY_LIMIT,
    )
    result = summarize(
        cycle=cycle.as_view(),
        categories=list_categories(sub),
        budgets=budgets,
        transactions=txns,
    )
    if len(txns) >= TXN_QUERY_LIMIT:
        # Single-page read ([B-2]); at the cap the totals would under-report the cycle, and a
        # dashboard that quietly under-reports is worse than one that admits it.
        result["totals"]["truncated"] = True
    logger.info(json.dumps({
        "route": "GET /cycles/{ref}/summary", "sub": sub, "cycleId": cycle.cycle_id,
        "txns": len(txns), "budgets": len(budgets),
    }))
    return _response(200, result)


def _set_budget(sub: str, cycle_ref: str, category_id: str, body: dict) -> dict:
    """AP 5 — set or clear one category's budget for one cycle (FR-4.3).

    `amountCents: null` clears it: "no budget" is the *absence* of the item (§2.3), and storing
    a zero instead would render as a $0 target that everything is instantly over.
    """
    settings = get_or_create_settings(sub)
    cycle = _resolve_cycle(settings["cadences"], cycle_ref)

    # Budgets key off a category id; an unknown one would write an orphan item that no
    # dashboard row ever reads. Archived categories are still writable — an archived category
    # can hold history for a cycle that was budgeted while it was live.
    if category_id not in {c["categoryId"] for c in list_categories(sub)}:
        raise ValueError("unknown categoryId")

    if "amountCents" not in body:
        raise ValueError("amountCents is required (use null to clear the budget)")
    amount = body["amountCents"]

    if amount is None:
        delete_budget(sub, cycle.cycle_id, category_id)
        logger.info(json.dumps({
            "route": "PUT /cycles/{ref}/budgets/{cat}", "sub": sub,
            "cycleId": cycle.cycle_id, "categoryId": category_id, "outcome": "cleared",
        }))
        return _response(200, {"cycle": cycle.as_view(), "budget": None})

    budget = put_budget(sub, cycle.cycle_id, category_id, amount)
    logger.info(json.dumps({
        "route": "PUT /cycles/{ref}/budgets/{cat}", "sub": sub,
        "cycleId": cycle.cycle_id, "categoryId": category_id, "amountCents": amount,
    }))
    return _response(200, {"cycle": cycle.as_view(), "budget": budget})


def _resolve_cycle(cadences: list[dict], cycle_ref: str):
    """`current` or an ISO date inside the cycle → the resolved Cycle (see the module docstring)."""
    if cycle_ref == CURRENT:
        return cycle_for(cadences, today_utc())
    if not _ISO_DATE.match(cycle_ref or ""):
        raise ValueError("cycle must be 'current' or an ISO date (YYYY-MM-DD) inside the cycle")
    try:
        on = date.fromisoformat(cycle_ref)
    except ValueError as err:
        raise ValueError("cycle date is not a real date") from err
    return cycle_for(cadences, on)


def _sub_from_event(event: dict) -> str | None:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _method(event: dict) -> str:
    return event.get("requestContext", {}).get("http", {}).get("method", "GET")


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError("request body must be valid JSON") from err
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
