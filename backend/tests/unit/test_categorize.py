"""Unit tests for the pure categorization domain (FR-3) — no AWS, no live model.

Covers the decision matrix (architecture §3.2), the merchant-rule seam, and the prompt/
structured-output contract. These are the surface the eval harness and the categorizer Lambda
both build on, so they're the high-value tests to get right before any Bedrock call.
"""
from core import merchant_rules
from core.categorize import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    SOURCE_LLM,
    SOURCE_RULE,
    decide_llm,
    decide_rule_hit,
)
from core.categorize.prompt import TOOL_NAME, build_request, parse_tool_use
from core.transactions import (
    STATUS_AUTO,
    STATUS_UNCATEGORIZED,
    gsi1_keys,
    gsi2_keys,
)

VALID = {"01CATFOOD", "01CATRENT"}


# --- decision matrix (architecture §3.2) -----------------------------------------------

def test_rule_hit_is_full_confidence_auto_no_review():
    d = decide_rule_hit("01CATFOOD")
    assert d.category_id == "01CATFOOD"
    assert d.status == STATUS_AUTO
    assert d.needs_review is False
    assert d.confidence == 1.0
    assert d.source == SOURCE_RULE


def test_llm_valid_high_confidence_auto_not_flagged():
    d = decide_llm("01CATFOOD", 0.93, valid_category_ids=VALID)
    assert d.category_id == "01CATFOOD"
    assert d.status == STATUS_AUTO
    assert d.needs_review is False
    assert d.source == SOURCE_LLM


def test_llm_valid_low_confidence_keeps_guess_but_flags_review():
    d = decide_llm("01CATRENT", 0.4, valid_category_ids=VALID)
    assert d.category_id == "01CATRENT"
    assert d.status == STATUS_AUTO  # a kept best-guess
    assert d.needs_review is True


def test_llm_confidence_exactly_at_threshold_is_auto_accepted():
    d = decide_llm("01CATFOOD", DEFAULT_CONFIDENCE_THRESHOLD, valid_category_ids=VALID)
    assert d.needs_review is False


def test_llm_null_category_is_uncategorized_and_flagged():
    d = decide_llm(None, 0.9, valid_category_ids=VALID)
    assert d.category_id is None
    assert d.status == STATUS_UNCATEGORIZED
    assert d.needs_review is True


def test_llm_unknown_category_id_degrades_to_uncategorized():
    # A hallucinated id the owner does not have → nothing mis-filed (FR-3.5).
    d = decide_llm("01CATHALLUCINATED", 0.99, valid_category_ids=VALID)
    assert d.category_id is None
    assert d.status == STATUS_UNCATEGORIZED
    assert d.needs_review is True


def test_llm_confidence_out_of_range_is_clamped():
    assert decide_llm("01CATFOOD", 1.7, valid_category_ids=VALID).confidence == 1.0
    assert decide_llm("01CATFOOD", -0.3, valid_category_ids=VALID).confidence == 0.0


def test_llm_non_numeric_confidence_becomes_zero_and_flags_review():
    d = decide_llm("01CATFOOD", "high", valid_category_ids=VALID)  # type: ignore[arg-type]
    assert d.confidence == 0.0
    assert d.needs_review is True


def test_custom_threshold_is_honored():
    # At threshold 0.95, a 0.9 guess should now flag for review.
    d = decide_llm("01CATFOOD", 0.9, valid_category_ids=VALID, threshold=0.95)
    assert d.needs_review is True


# --- merchant rules ---------------------------------------------------------------------

def test_rule_sk_uses_normalized_merchant_verbatim():
    assert merchant_rules.rule_sk("blue bottle cof") == "RULE#blue bottle cof"


def test_rule_category_none_on_miss():
    assert merchant_rules.rule_category(None) is None
    assert merchant_rules.rule_category({}) is None


def test_rule_category_returns_mapped_category():
    rule = merchant_rules.new_rule("blue bottle cof", "01CATFOOD", updated_at="2026-07-21T00:00:00Z")
    assert merchant_rules.rule_category(rule) == "01CATFOOD"
    assert rule["type"] == "RULE"
    assert rule["source"] == merchant_rules.SOURCE_CORRECTION


# --- GSI key helpers --------------------------------------------------------------------

def test_gsi1_keys_encode_category_drilldown():
    keys = gsi1_keys("a1b2", "01CATFOOD", "2026-07-03", "9f2ac41e07b1d3aa")
    assert keys == {
        "gsi1pk": "USER#a1b2#CAT#01CATFOOD",
        "gsi1sk": "TXN#2026-07-03#9f2ac41e07b1d3aa",
    }


def test_gsi2_keys_encode_review_queue():
    keys = gsi2_keys("a1b2", "2026-07-03", "9f2ac41e07b1d3aa")
    assert keys == {
        "gsi2pk": "USER#a1b2#REVIEW",
        "gsi2sk": "TXN#2026-07-03#9f2ac41e07b1d3aa",
    }


# --- prompt / structured-output contract ------------------------------------------------

_CATEGORIES = [{"categoryId": "01CATFOOD", "name": "Groceries"}, {"categoryId": "01CATRENT", "name": "Housing"}]
_TXNS = [
    {"txnId": "aaa", "merchantNormalized": "trader joes", "descriptionRaw": "TRADER JOES #123",
     "amountCents": -4210, "direction": "debit"},
    {"txnId": "bbb", "merchantNormalized": "acme rentals", "descriptionRaw": "ACME RENTALS",
     "amountCents": -120000, "direction": "debit"},
]


def test_build_request_shape_and_forced_tool():
    req = build_request(_TXNS, categories=_CATEGORIES)
    assert set(req) == {"system", "messages", "tools", "tool_choice"}
    assert req["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    # Categories appear by id in the system prompt; txns appear by id in the user message.
    assert "01CATFOOD" in req["system"] and "Groceries" in req["system"]
    assert "aaa" in req["messages"][0]["content"] and "trader joes" in req["messages"][0]["content"]
    # The tool schema must require one result-array per call.
    schema = req["tools"][0]["input_schema"]
    assert schema["required"] == ["categorizations"]


def test_build_request_includes_corrections_when_present():
    req = build_request(_TXNS, categories=_CATEGORIES,
                        corrections=[{"merchantNormalized": "trader joes", "categoryName": "Groceries"}])
    assert "trader joes -> Groceries" in req["system"]


def test_parse_tool_use_normalizes_entries():
    parsed = parse_tool_use({"categorizations": [
        {"txnId": "aaa", "categoryId": "01CATFOOD", "confidence": 0.9},
        {"txnId": "bbb", "categoryId": None, "confidence": 0.2},
    ]})
    assert parsed == [
        {"txnId": "aaa", "categoryId": "01CATFOOD", "confidence": 0.9},
        {"txnId": "bbb", "categoryId": None, "confidence": 0.2},
    ]


def test_parse_tool_use_drops_junk_and_coerces():
    parsed = parse_tool_use({"categorizations": [
        {"txnId": "", "categoryId": "x", "confidence": 1},   # blank txnId → dropped
        "not-a-dict",                                          # non-dict → dropped
        {"txnId": "ccc", "categoryId": "", "confidence": "nope"},  # blank cat→None, junk conf→0.0
    ]})
    assert parsed == [{"txnId": "ccc", "categoryId": None, "confidence": 0.0}]


def test_parse_tool_use_empty_or_missing_is_empty_list():
    assert parse_tool_use({}) == []
    assert parse_tool_use({"categorizations": None}) == []
