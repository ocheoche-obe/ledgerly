"""Categorizer Lambda (SQS-triggered) — categorize imported transactions (FR-3).

Consumes the categorization queue the importer feeds (architecture §3.2). Each SQS message is a
batch of locate keys ``{sub, txnKeys: [{date, txnId}]}``; per message:

  1. load the owner's active categories (the valid target set)
  2. read each transaction; process only the still-``uncategorized`` ones (a replay of an
     already-categorized batch is a cheap no-op — idempotency, NFR-3.2)
  3. **merchant rules first** — an exact ``RULE#<merchant>`` hit skips the LLM (free, FR-3.4).
     Empty this slice (rules land in Slice 7), so everything falls through to:
  4. **the LLM** — one batched Bedrock call (Claude Opus 4.8) returns ``{categoryId?, confidence}``
     per txn; ``decide_llm`` applies the confidence threshold and validates the id
  5. persist each decision (correction-preserving conditional update, GSI maintenance)

Failures never lose data (FR-3.5): a message that raises is reported via partial-batch-failure
so only *it* redelivers (→ DLQ after 3 tries); its transactions simply stay ``uncategorized``.
Both `bedrock` and the queue use IAM-role auth — zero runtime secrets (ADR-008).
"""
from __future__ import annotations

import json
import logging
import os

from adapters.bedrock import BedrockCategorizer
from adapters.dynamo import (
    apply_categorization,
    get_rule,
    get_transaction,
    list_category_choices,
)
from core.categorize import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    SOURCE_RULE,
    decide_llm,
    decide_rule_hit,
)
from core.merchant_rules import rule_category
from core.transactions import STATUS_UNCATEGORIZED

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-level so the boto3/Bedrock client is created once per warm container; tests inject a
# fake via `handler._categorizer = ...`.
_categorizer = BedrockCategorizer()


def _threshold() -> float:
    """Confidence threshold, env-overridable (⚠ Slice-5 decision; default 0.8)."""
    try:
        return float(os.environ.get("CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD))
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD


def handler(event: dict, context) -> dict:
    """SQS batch entrypoint. Returns partial-batch-failure ids so a bad message redelivers
    alone (the event source mapping must have ReportBatchItemFailures enabled)."""
    failures: list[dict] = []
    for record in event.get("Records", []):
        try:
            _process_message(record.get("body", "{}"))
        except Exception:
            logger.exception(json.dumps({"stage": "categorizer", "messageId": record.get("messageId")}))
            failures.append({"itemIdentifier": record.get("messageId")})
    return {"batchItemFailures": failures}


def _process_message(body: str) -> None:
    msg = json.loads(body)
    sub = msg["sub"]
    txn_keys = msg.get("txnKeys", [])
    if not txn_keys:
        return

    categories = list_category_choices(sub)
    valid_ids = {c["categoryId"] for c in categories}
    threshold = _threshold()

    rule_hits = 0
    llm_txns: list[dict] = []           # transactions with no rule → go to the LLM (full items)

    for key in txn_keys:
        txn = get_transaction(sub, key["date"], key["txnId"])
        if txn is None or txn.get("categoryStatus") != STATUS_UNCATEGORIZED:
            # Missing (shouldn't happen) or already handled (auto/confirmed/corrected) → skip.
            continue

        category_id = rule_category(get_rule(sub, txn.get("merchantNormalized", "")))
        if category_id is not None:
            apply_categorization(sub, txn["date"], txn["txnId"], decide_rule_hit(category_id))
            rule_hits += 1
        else:
            llm_txns.append(txn)

    llm_auto = needs_review = 0
    if llm_txns:
        results = {r["txnId"]: r for r in _categorizer.categorize(
            llm_txns, categories=categories, corrections=[])}
        for txn in llm_txns:
            result = results.get(txn["txnId"], {})
            decision = decide_llm(
                result.get("categoryId"), result.get("confidence", 0.0),
                valid_category_ids=valid_ids, threshold=threshold,
            )
            apply_categorization(sub, txn["date"], txn["txnId"], decision)
            if decision.needs_review:
                needs_review += 1
            elif decision.source != SOURCE_RULE:
                llm_auto += 1

    logger.info(json.dumps({
        "stage": "categorizer", "sub_txns": len(txn_keys),
        "rule_hits": rule_hits, "llm_auto": llm_auto, "needs_review": needs_review,
    }))
