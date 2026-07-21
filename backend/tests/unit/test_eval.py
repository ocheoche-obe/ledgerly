"""Unit tests for the eval harness scoring logic (eval/harness.py) — no Bedrock.

Proves the harness scores predictions the same way production would store them (a low-confidence
correct guess counts as correct; a null/invalid result counts as a miss), using a fake model.
This is what lets CI keep the accuracy gate honest without a live Bedrock call.
"""
from eval.harness import evaluate, predict, score

CATEGORIES = [
    {"categoryId": "01CATFOOD", "name": "Groceries"},
    {"categoryId": "01CATRENT", "name": "Housing"},
]
TXNS = [
    {"txnId": "a", "merchantNormalized": "trader joes", "descriptionRaw": "TJ", "amountCents": -100, "direction": "debit"},
    {"txnId": "b", "merchantNormalized": "acme rentals", "descriptionRaw": "ACME", "amountCents": -1000, "direction": "debit"},
    {"txnId": "c", "merchantNormalized": "???", "descriptionRaw": "???", "amountCents": -5, "direction": "debit"},
]
TRUTH = {"a": "01CATFOOD", "b": "01CATRENT", "c": "01CATFOOD"}


class FakeCategorizer:
    def __init__(self, mapping):
        self.mapping = mapping

    def categorize(self, transactions, *, categories, corrections):
        return [{"txnId": t["txnId"], "categoryId": self.mapping[t["txnId"]][0],
                 "confidence": self.mapping[t["txnId"]][1]} for t in transactions]


def test_perfect_predictions_score_full_accuracy():
    fake = FakeCategorizer({"a": ("01CATFOOD", 0.95), "b": ("01CATRENT", 0.9), "c": ("01CATFOOD", 0.85)})
    result = evaluate(fake, "fake", TXNS, CATEGORIES, TRUTH)
    assert result.accuracy == 1.0
    assert result.correct == 3
    assert result.uncategorized == 0
    assert result.needs_review == 0


def test_low_confidence_correct_guess_still_counts_correct_but_flags_review():
    # 'a' is correct but under threshold → counts correct AND is flagged for review.
    fake = FakeCategorizer({"a": ("01CATFOOD", 0.3), "b": ("01CATRENT", 0.9), "c": ("01CATFOOD", 0.9)})
    result = evaluate(fake, "fake", TXNS, CATEGORIES, TRUTH)
    assert result.correct == 3
    assert result.needs_review == 1


def test_null_and_invalid_predictions_are_misses_and_uncategorized():
    fake = FakeCategorizer({"a": (None, 0.9), "b": ("01NOTACAT", 0.99), "c": ("01CATFOOD", 0.9)})
    result = evaluate(fake, "fake", TXNS, CATEGORIES, TRUTH)
    assert result.correct == 1                 # only 'c'
    assert result.uncategorized == 2           # null + invalid both degrade to uncategorized
    assert round(result.accuracy, 3) == round(1 / 3, 3)


def test_wrong_category_is_a_miss_not_uncategorized():
    fake = FakeCategorizer({"a": ("01CATRENT", 0.95), "b": ("01CATRENT", 0.95), "c": ("01CATFOOD", 0.95)})
    result = evaluate(fake, "fake", TXNS, CATEGORIES, TRUTH)
    assert result.correct == 2                 # 'a' mis-categorized to rent
    assert result.uncategorized == 0           # it has a (wrong) category, not uncategorized


def test_predict_returns_a_decision_per_txn():
    fake = FakeCategorizer({"a": ("01CATFOOD", 0.9), "b": ("01CATRENT", 0.9), "c": (None, 0.1)})
    decisions = predict(fake, TXNS, CATEGORIES)
    assert set(decisions) == {"a", "b", "c"}
    assert decisions["c"].category_id is None


def test_score_is_separable_from_prediction():
    # score() takes decisions + truth directly — usable for offline/recorded predictions.
    fake = FakeCategorizer({"a": ("01CATFOOD", 0.9), "b": ("01CATRENT", 0.9), "c": ("01CATFOOD", 0.9)})
    decisions = predict(fake, TXNS, CATEGORIES)
    result = score("m", decisions, TRUTH)
    assert result.total == 3 and result.correct == 3
