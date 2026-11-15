"""Async Lambda invoke adapter — hands a Plaid sync to the worker (ADR-014).

The API Lambda answers within API Gateway's 30-second limit by *starting* a sync and
returning an import ID; the work runs in the ``plaid_sync`` worker, invoked asynchronously.
The payload carries locate keys only (``sub``, ``itemId``, ``importId``) — never a token.
"""
from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config

_client = boto3.client(
    "lambda",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)


def start_plaid_sync(*, sub: str, item_id: str, import_id: str) -> None:
    """Queue one sync on the worker. Raises if the invoke itself is rejected."""
    _client.invoke(
        FunctionName=os.environ["PLAID_SYNC_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"sub": sub, "itemId": item_id, "importId": import_id}).encode(),
    )
