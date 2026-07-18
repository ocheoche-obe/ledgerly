"""/settings — GET the owner's PROFILE, PATCH the budget-cycle cadence (FR-4.2).

Thin handler (architecture §5.2): identity comes only from the JWT claims the API Gateway
authorizer already verified — never from the path/query/body (FR-1.3). Business logic
(cadence planning, cycle resolution) lives in `core/`; persistence in `adapters/`.

The response enriches the stored settings with the *current* cycle, computed live from the
cadence history — so the SPA can show "you're in M#2026-07 (Jul 1–31)" without its own date
math, and it doubles as a live check that the cycle engine works in the deployed app.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from adapters.dynamo import get_or_create_settings, update_cadence
from core.cycles import cycle_for

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/settings", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    method = _method(event)
    if method == "GET":
        view = get_or_create_settings(sub)
        logger.info(json.dumps({"route": "GET /settings", "sub": sub, "outcome": "ok"}))
        return _response(200, _with_current_cycle(view))

    if method == "PATCH":
        try:
            body = _parse_body(event)
            cadence = body.get("cadence") or {}
            if not isinstance(cadence, dict):
                raise ValueError("cadence must be an object")
            kind = cadence.get("kind")
            if kind not in ("monthly", "biweekly"):
                raise ValueError("cadence.kind must be 'monthly' or 'biweekly'")
            view = update_cadence(sub, kind=kind, anchor=cadence.get("anchor"))
        except ValueError as err:
            logger.info(json.dumps({"route": "PATCH /settings", "sub": sub, "err": str(err)}))
            return _response(400, {"message": str(err)})
        logger.info(json.dumps({"route": "PATCH /settings", "sub": sub, "outcome": "ok"}))
        return _response(200, _with_current_cycle(view))

    return _response(405, {"message": "Method not allowed"})


def _with_current_cycle(view: dict) -> dict:
    """Attach the cycle in force today, derived from the cadence history."""
    return {**view, "currentCycle": cycle_for(view["cadences"], date.today()).as_view()}


def _sub_from_event(event: dict) -> str | None:
    """Extract the verified Cognito subject from HTTP API (payload v2) JWT claims."""
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
