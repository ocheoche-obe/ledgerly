"""GET /settings — return the owner's PROFILE, creating a default on first call.

Thin handler (architecture §5.2): it reads the caller's identity from the JWT claims the
API Gateway authorizer already verified — never from the path/query/body (FR-1.3) — then
delegates to the persistence adapter. No secrets, no PII beyond the opaque Cognito `sub`
in logs.
"""
from __future__ import annotations

import json
import logging

from adapters.dynamo import get_or_create_settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        # The authorizer should make this unreachable; defense in depth — never serve data
        # without a verified identity.
        logger.warning(json.dumps({"route": "GET /settings", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    settings = get_or_create_settings(sub)
    logger.info(json.dumps({"route": "GET /settings", "sub": sub, "outcome": "ok"}))
    return _response(200, settings)


def _sub_from_event(event: dict) -> str | None:
    """Extract the verified Cognito subject from HTTP API (payload v2) JWT claims."""
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
