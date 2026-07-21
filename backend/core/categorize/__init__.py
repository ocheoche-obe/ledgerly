"""Categorization domain (FR-3) — pure Python, no AWS imports.

This package owns the *interface* and the *decision logic* of AI categorization; the concrete
model call (Bedrock / Claude Opus 4.8) lives in ``adapters/bedrock.py`` behind the
``Categorizer`` protocol, so swapping model or provider is a config + adapter change, not a
rewrite (ADR-008, NFR-6.1). The split mirrors the portability seam (architecture §5.2):
``core/`` decides *what* a categorization means; ``adapters/`` performs the SDK call.

Pipeline (architecture §3.2), per transaction:

  1. merchant-rule hit? → ``decide_rule_hit`` (category, confidence 1.0, auto, no review)
  2. otherwise the LLM returns ``{categoryId?, confidence}`` → ``decide_llm`` applies the
     confidence threshold and validates the category id against the owner's real categories:
       • valid id, conf ≥ threshold → ``auto``, not flagged
       • valid id, conf < threshold → ``auto`` but ``needsReview`` (a kept best-guess)
       • null / unknown id           → ``uncategorized`` + ``needsReview`` (nothing lost, FR-3.5)

A ``Decision`` is a pure value; the adapter turns it into the DynamoDB update (GSI keys,
correction-preserving condition). Failures never reach here — a model/infra failure leaves the
transaction ``uncategorized`` via the SQS→DLQ path (architecture §4.5), never destroyed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.transactions import STATUS_AUTO, STATUS_UNCATEGORIZED

# Default confidence threshold (⚠ Slice-5 decision, owner-approved 2026-07-21): at/above it a
# categorization is auto-accepted; below it the txn is kept but flagged for review. Tuned
# against the eval harness this slice; if a different value ships it gets an ADL note.
DEFAULT_CONFIDENCE_THRESHOLD = 0.8

SOURCE_RULE = "rule"
SOURCE_LLM = "llm"


@dataclass(frozen=True)
class Decision:
    """The outcome of categorizing one transaction — a pure value the adapter persists.

    ``category_id`` is None only when the txn stays uncategorized (null/unknown LLM result).
    ``needs_review`` drives the sparse GSI2 review-queue keys; ``source`` is for metrics
    (rule-hit vs llm-auto vs needs-review — architecture §4.1).
    """
    category_id: str | None
    status: str
    needs_review: bool
    confidence: float
    source: str


class Categorizer(Protocol):
    """The swappable model seam (ADR-008). An implementation takes the batch of transactions
    to categorize plus the owner's categories and recent corrections (few-shot), and returns
    one raw result per transaction, keyed by ``txnId``.

    ``transactions``: ``[{"txnId", "merchantNormalized", "descriptionRaw", "amountCents",
    "direction"}, ...]``. ``categories``: ``[{"categoryId", "name"}, ...]``. ``corrections``:
    recent ``[{"merchantNormalized", "categoryName"}]`` few-shot examples (empty this slice).

    Returns ``[{"txnId": str, "categoryId": str | None, "confidence": float}, ...]`` — the
    caller maps these through :func:`decide_llm`. Implementations must be side-effect free
    beyond the model call; they never write the table.
    """

    def categorize(
        self,
        transactions: list[dict],
        *,
        categories: list[dict],
        corrections: list[dict],
    ) -> list[dict]: ...


def decide_rule_hit(category_id: str) -> Decision:
    """A merchant-rule match — an exact, owner-taught mapping. Full confidence, no review."""
    return Decision(
        category_id=category_id,
        status=STATUS_AUTO,
        needs_review=False,
        confidence=1.0,
        source=SOURCE_RULE,
    )


def decide_llm(
    category_id: str | None,
    confidence: float,
    *,
    valid_category_ids: set[str],
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Decision:
    """Turn one raw LLM result into a persisted :class:`Decision` (architecture §3.2).

    A null or unknown ``category_id`` (the model declined or hallucinated an id the owner
    doesn't have) lands ``uncategorized`` + ``needsReview`` — nothing is mis-filed, and the
    owner sees it in the review queue (FR-3.5). A valid id below the threshold keeps the guess
    but flags it; at/above the threshold it is auto-accepted.
    """
    conf = _clamp01(confidence)

    if category_id is None or category_id not in valid_category_ids:
        return Decision(
            category_id=None,
            status=STATUS_UNCATEGORIZED,
            needs_review=True,
            confidence=conf,
            source=SOURCE_LLM,
        )

    return Decision(
        category_id=category_id,
        status=STATUS_AUTO,
        needs_review=conf < threshold,
        confidence=conf,
        source=SOURCE_LLM,
    )


def _clamp01(value: float) -> float:
    """Coerce a model-supplied confidence into [0, 1]; a non-number becomes 0.0 (treated as
    lowest confidence, so it flags for review rather than silently auto-accepting)."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
