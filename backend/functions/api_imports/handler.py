"""/imports — request an upload URL and poll import status (FR-2.5).

Thin handler (architecture §5.2): identity from verified JWT claims only (FR-1.3); the
account label is validated + normalized in `core/`, persistence + presigning in `adapters/`.

Routes (all authorized by the API Gateway JWT authorizer):
  POST /imports          → {filename, accountLabel} → {importId, uploadUrl} (presigned S3 PUT)
  GET  /imports          → recent imports, newest first
  GET  /imports/{id}     → one import's status + counts (UI polls this)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from adapters.dynamo import create_import, get_import, list_imports
from adapters.s3 import generate_upload_url, upload_key
from core.accounts import clean_account_label, normalize_account_id
from core.ids import new_ulid

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    sub = _sub_from_event(event)
    if not sub:
        logger.warning(json.dumps({"route": "/imports", "outcome": "no_sub"}))
        return _response(401, {"message": "Unauthorized"})

    method = _method(event)
    try:
        if method == "POST":
            return _create(sub, event)
        if method == "GET":
            import_id = (event.get("pathParameters") or {}).get("id")
            if import_id:
                view = get_import(sub, import_id)
                if view is None:
                    return _response(404, {"message": "import not found"})
                return _response(200, view)
            return _response(200, {"imports": list_imports(sub)})
    except ValueError as err:
        logger.info(json.dumps({"route": f"{method} /imports", "sub": sub, "err": str(err)}))
        return _response(400, {"message": str(err)})

    return _response(405, {"message": "Method not allowed"})


def _create(sub: str, event: dict) -> dict:
    body = _parse_body(event)
    filename = str(body.get("filename", "")).strip()
    if not filename:
        raise ValueError("filename is required")
    account_label = clean_account_label(body.get("accountLabel", ""))
    account_id = normalize_account_id(account_label)

    import_id = new_ulid()
    created = create_import(
        sub, import_id,
        filename=filename,
        account_label=account_label,
        account_id=account_id,
        object_key=upload_key(sub, import_id),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    upload_url = generate_upload_url(sub, import_id)
    logger.info(json.dumps({"route": "POST /imports", "sub": sub, "importId": import_id}))
    return _response(201, {"importId": import_id, "uploadUrl": upload_url, **created})


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
