"""Eval harness scoring logic (NFR-5.3) — pure Python, no AWS imports.

The gate that makes categorization *measured, not vibes*: given a ``Categorizer`` and a labeled
set of transactions, run predictions through the *same* decision logic production uses
(:func:`core.categorize.decide_llm`) and score them against the owner's ground truth. Keeping
this pure means the harness itself is unit-tested with a fake model (no Bedrock in CI), while
the real run (``eval/run.py``) points the same functions at Claude Opus 4.8 and Sonnet 5.

Accuracy is measured on the *predicted category* after the threshold + validity rules, so the
number reflects what the pipeline would actually store — a low-confidence-but-correct guess
counts as correct (it lands on the transaction); a null/invalid result counts as a miss.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.categorize import DEFAULT_CONFIDENCE_THRESHOLD, decide_llm


@dataclass(frozen=True)
class EvalResult:
    """One model's scorecard over a labeled set."""
    model: str
    total: int
    correct: int
    needs_review: int
    uncategorized: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def review_rate(self) -> float:
        return self.needs_review / self.total if self.total else 0.0


def predict(
    categorizer,
    transactions: list[dict],
    categories: list[dict],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict:
    """Run the model + the production decision rules → ``{txnId: Decision}``.

    Mirrors the categorizer Lambda exactly (rule lookups are omitted — the eval measures the
    *model*, not the owner's learned rules): every txn goes to the model, and each raw result
    is mapped through :func:`decide_llm` so the scored prediction is the one that would persist.
    """
    valid = {c["categoryId"] for c in categories}
    raw = categorizer.categorize(transactions, categories=categories, corrections=[])
    by_id = {r["txnId"]: r for r in raw}
    decisions = {}
    for txn in transactions:
        result = by_id.get(txn["txnId"], {})
        decisions[txn["txnId"]] = decide_llm(
            result.get("categoryId"), result.get("confidence", 0.0),
            valid_category_ids=valid, threshold=threshold,
        )
    return decisions


def score(model: str, decisions: dict, truth: dict) -> EvalResult:
    """Score predictions against ground truth ``{txnId: trueCategoryId}``."""
    correct = needs_review = uncategorized = 0
    for txn_id, true_category in truth.items():
        decision = decisions.get(txn_id)
        predicted = decision.category_id if decision else None
        if predicted == true_category:
            correct += 1
        if predicted is None:
            uncategorized += 1
        if decision and decision.needs_review:
            needs_review += 1
    return EvalResult(
        model=model, total=len(truth), correct=correct,
        needs_review=needs_review, uncategorized=uncategorized,
    )


def evaluate(
    categorizer,
    model: str,
    transactions: list[dict],
    categories: list[dict],
    truth: dict,
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> EvalResult:
    """Predict + score in one call — the per-model entry point the runner loops over."""
    decisions = predict(categorizer, transactions, categories, threshold=threshold)
    return score(model, decisions, truth)
