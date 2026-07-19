"""/transactions — list transactions in a date window (FR-2, AP 6).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3). This slice
is a read-only list to prove imports landed; filters/search + drill-down come in Slice 7.

Routes (authorized by the API Gateway JWT authorizer):
  GET /transactions?from=YYYY-MM-DD&to=YYYY-MM-DD   → transactions in [from, to], oldest first
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from adapters.dynamo import query_transactions

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Default span when the caller omits from/to. 90 days comfortably covers a just-imported
# month plus the prior one, so a fresh import reliably shows in the basic list. Browsing
# arbitrary older ranges (and pagination beyond the query cap) arrives with filters in Slice 7.
_DEFAULT_WINDOW_DAYS = 90


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/transactions", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    params = event.get("queryStringParameters") or {}
    try:
        date_from, date_to = _window(params.get("from"), params.get("to"))
    except ValueError as err:
        return _response(400, {"message": str(err)})

    txns = query_transactions(sub, date_from=date_from, date_to=date_to)
    logger.info(json.dumps({
        "route": "GET /transactions", "sub": sub, "from": date_from, "to": date_to,
        "count": len(txns),
    }))
    return _response(200, {"transactions": txns, "from": date_from, "to": date_to})


def _window(raw_from: str | None, raw_to: str | None) -> tuple[str, str]:
    """Resolve the [from, to] window, defaulting to the last ~45 days. Validates ISO dates."""
    today = date.today()
    date_to = _valid_date(raw_to, "to") if raw_to else today.isoformat()
    date_from = (
        _valid_date(raw_from, "from") if raw_from
        else (date.fromisoformat(date_to) - timedelta(days=_DEFAULT_WINDOW_DAYS)).isoformat()
    )
    if date_from > date_to:
        raise ValueError("'from' must not be after 'to'")
    return date_from, date_to


def _valid_date(value: str, field: str) -> str:
    if not _ISO_DATE.match(value):
        raise ValueError(f"'{field}' must be an ISO date (YYYY-MM-DD)")
    try:
        date.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"'{field}' is not a real date") from err
    return value


def _sub_from_event(event: dict) -> str | None:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
