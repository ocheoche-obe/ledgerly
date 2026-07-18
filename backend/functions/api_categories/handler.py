"""/categories — list, create, rename, and archive spending categories (FR-4.1).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3); domain
rules (name validation, starter seeding) live in `core/` + `adapters/`.

Routes (all authorized by the API Gateway JWT authorizer):
  GET   /categories          → list active + archived (seeds the starter set on first run)
  POST  /categories          → create {name}
  PATCH /categories/{id}     → rename and/or archive {name?, status?}
"""
from __future__ import annotations

import json
import logging

from adapters.dynamo import create_category, list_categories, update_category

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/categories", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    method = _method(event)
    try:
        if method == "GET":
            return _response(200, {"categories": list_categories(sub)})

        if method == "POST":
            body = _parse_body(event)
            created = create_category(sub, body.get("name", ""))
            logger.info(json.dumps({"route": "POST /categories", "sub": sub, "outcome": "ok"}))
            return _response(201, created)

        if method == "PATCH":
            category_id = (event.get("pathParameters") or {}).get("id")
            if not category_id:
                return _response(400, {"message": "missing category id in path"})
            body = _parse_body(event)
            updated = update_category(
                sub, category_id, name=body.get("name"), status=body.get("status")
            )
            if updated is None:
                return _response(404, {"message": "category not found"})
            logger.info(
                json.dumps({"route": "PATCH /categories/{id}", "sub": sub, "outcome": "ok"})
            )
            return _response(200, updated)
    except ValueError as err:
        logger.info(json.dumps({"route": f"{method} /categories", "sub": sub, "err": str(err)}))
        return _response(400, {"message": str(err)})

    return _response(405, {"message": "Method not allowed"})


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
