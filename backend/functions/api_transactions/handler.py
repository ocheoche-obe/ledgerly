"""/transactions — list transactions in a date window, and re-drive categorization (AP 6).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3).

Routes (authorized by the API Gateway JWT authorizer):
  GET  /transactions?from=YYYY-MM-DD&to=YYYY-MM-DD  → transactions in [from, to], oldest first
  POST /transactions/recategorize {from, to, includeCategorized?}
       → re-enqueue matching transactions for the categorizer ([B-7], FR-3)

**Why recategorize exists ([B-7]):** the importer enqueues only the rows it *newly added*, so
categorization could previously only ever happen at import time. Transactions imported before
the categorizer existed were stranded — and ADR-012 idempotency means re-uploading the same
export adds 0 rows and therefore enqueues 0, so no re-import can rescue them. This is the
re-drive path. It is an endpoint rather than a one-off script because Slice 7's review queue
needs the same "recategorize these" capability.

Safe to run repeatedly by construction: it only enqueues, the categorizer is idempotent, and
`apply_categorization` refuses to overwrite an owner's `confirmed`/`corrected` decision (AP 10).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from adapters.dynamo import TXN_QUERY_LIMIT, query_transactions
from adapters.sqs import enqueue_categorization
from core.cycles import today_utc
from core.transactions import OWNER_SET_STATUSES, STATUS_UNCATEGORIZED

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

    method = _method(event)
    try:
        if method == "GET":
            return _list(sub, event.get("queryStringParameters") or {})
        if method == "POST":
            return _recategorize(sub, _parse_body(event))
    except ValueError as err:
        logger.info(json.dumps({"route": f"{method} /transactions", "sub": sub, "err": str(err)}))
        return _response(400, {"message": str(err)})

    return _response(405, {"message": "Method not allowed"})


def _list(sub: str, params: dict) -> dict:
    date_from, date_to = _window(params.get("from"), params.get("to"))
    txns = query_transactions(sub, date_from=date_from, date_to=date_to)
    logger.info(json.dumps({
        "route": "GET /transactions", "sub": sub, "from": date_from, "to": date_to,
        "count": len(txns),
    }))
    return _response(200, {"transactions": txns, "from": date_from, "to": date_to})


def _recategorize(sub: str, body: dict) -> dict:
    """Re-enqueue the window's transactions for the categorizer. 202 — the work is async.

    Default scope is **uncategorized only**, so a mistyped window cannot disturb transactions
    the pipeline already filed. `includeCategorized: true` widens it to re-run `auto` ones as
    well (useful after a model or prompt change, and the capability Slice 7's review queue
    needs); owner-set statuses are excluded from *both* scopes.
    """
    include_categorized = _bool_field(body.get("includeCategorized"), "includeCategorized")
    date_from, date_to = _window(body.get("from"), body.get("to"))

    txns = query_transactions(sub, date_from=date_from, date_to=date_to, limit=TXN_QUERY_LIMIT)
    eligible = [t for t in txns if _eligible(t, include_categorized=include_categorized)]
    keys = [{"date": t["date"], "txnId": t["txnId"]} for t in eligible]
    messages = enqueue_categorization(sub, keys, force=include_categorized)

    result = {
        "from": date_from,
        "to": date_to,
        "includeCategorized": include_categorized,
        "scanned": len(txns),
        "enqueued": len(keys),
        "messages": messages,
    }
    if len(txns) >= TXN_QUERY_LIMIT:
        # The window query is single-page ([B-2]); at the cap there may be more rows beyond it,
        # so say so rather than let a bulk backfill silently miss the tail.
        result["truncated"] = True
        result["message"] = (
            f"window hit the {TXN_QUERY_LIMIT}-transaction query cap — "
            "run again over narrower windows to cover the rest"
        )
    logger.info(json.dumps({"route": "POST /transactions/recategorize", "sub": sub, **result}))
    return _response(202, result)


def _eligible(txn: dict, *, include_categorized: bool) -> bool:
    status = txn.get("categoryStatus", STATUS_UNCATEGORIZED)
    if status in OWNER_SET_STATUSES:
        return False  # never re-run an owner decision — the write would be refused anyway
    return include_categorized or status == STATUS_UNCATEGORIZED


def _window(raw_from: str | None, raw_to: str | None) -> tuple[str, str]:
    """Resolve the [from, to] window, defaulting to the last ~90 days. Validates ISO dates."""
    today = today_utc()
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


def _bool_field(value, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"'{field}' must be true or false")
    return value


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
