"""SQS enqueue adapter — categorization jobs (ADR-009).

The import→categorization seam (architecture §3.2, §4.5): after the importer persists new
transactions it enqueues them for the categorizer Lambda. Messages carry *locate keys*
(``{sub, txnKeys: [{date, txnId}]}``), not transaction payloads — the DynamoDB item is the
source of truth, and the categorizer reads it back. Keys are chunked so one message is roughly
one LLM batch, bounding the categorizer's per-invocation Bedrock call.

Enqueue is **best-effort**: categorization must never block or fail an import (FR-3.5). If the
queue isn't configured, or a send fails, that is logged and swallowed by the caller — the
transactions are already safely persisted as ``uncategorized`` and can be re-driven later.
"""
from __future__ import annotations

import json
import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger()

_client = boto3.client(
    "sqs",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)

# Cap keys per message → the categorizer's LLM batch size. ~20 keeps the Bedrock prompt small
# and one bad batch cheap to retry; at ~500 txns/month this is a handful of messages per import.
_MAX_KEYS_PER_MESSAGE = 20


def enqueue_categorization(sub: str, txn_keys: list[dict], *, force: bool = False) -> int:
    """Enqueue categorization jobs for transactions. Returns the message count.

    ``txn_keys`` is ``[{"date", "txnId"}]`` (the locate keys the categorizer needs to read the
    stored item and form its sort key). A no-op that returns 0 when there is nothing to enqueue
    or the queue URL is unset (logged) — the caller treats any failure as non-fatal.

    ``force`` re-categorizes transactions the pipeline has *already* filed (Slice 6, [B-7]).
    It has to travel in the message because the skip lives in the categorizer, not here: that
    consumer ignores any transaction whose status isn't ``uncategorized`` so a redelivered SQS
    message is a cheap no-op. Owner decisions (``confirmed``/``corrected``) are still never
    re-run — see the categorizer and ``apply_categorization``'s conditional guard.
    """
    queue_url = os.environ.get("CATEGORIZE_QUEUE_URL")
    if not queue_url:
        logger.warning(json.dumps({"stage": "enqueue", "err": "CATEGORIZE_QUEUE_URL unset"}))
        return 0
    if not txn_keys:
        return 0

    sent = 0
    for chunk in _chunks(txn_keys, _MAX_KEYS_PER_MESSAGE):
        body: dict = {"sub": sub, "txnKeys": chunk}
        if force:
            body["force"] = True  # omitted when false → import messages keep their exact shape
        _client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
        sent += 1
    return sent


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
