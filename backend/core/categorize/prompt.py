"""Prompt + structured-output contract for LLM categorization — pure Python, no AWS imports.

Builds the request the ``Categorizer`` sends to the model and parses the structured result
back. Kept in ``core/`` because it is the *contract* (which fields, which schema, how a
category is chosen), not the transport: the Bedrock adapter wraps this in the invoke-model
envelope. Everything here is plain dicts, so it is unit-testable without AWS or a live model.

Structured output is a **forced tool call** (``record_categorizations``): the most portable
way to guarantee machine-readable output across Anthropic models on Bedrock (works whether or
not ``output_config.format`` is available for a given model version). The model must return one
entry per input transaction, each ``{txnId, categoryId|null, confidence}``.

The category id is deliberately *not* constrained by a schema ``enum``: the model is told the
valid ids and asked to use one or null, and :func:`core.categorize.decide_llm` treats any
unknown id as ``uncategorized`` (architecture §3.2). That is more robust than a strict enum —
a hallucinated id degrades to review-queue, never to a hard schema error that fails the batch.
"""
from __future__ import annotations

import json

TOOL_NAME = "record_categorizations"

_SYSTEM = (
    "You are a personal-finance categorization engine. You assign each bank transaction to "
    "exactly one of the owner's budget categories, or to nothing when you genuinely cannot "
    "tell.\n\n"
    "Rules:\n"
    "- Choose the single best category for each transaction from the list below.\n"
    "- Use the category's id (the value before the dash), never its name.\n"
    "- If no category is a reasonable fit, return null for categoryId — do not force a guess.\n"
    "- confidence is your calibrated probability the category is correct, 0.0 to 1.0. Be "
    "honest: use lower values when the merchant is ambiguous or unfamiliar.\n"
    "- Return exactly one result per transaction, matched by txnId.\n"
    "- Call the record_categorizations tool once with all results."
)


def build_request(
    transactions: list[dict],
    *,
    categories: list[dict],
    corrections: list[dict] | None = None,
) -> dict:
    """Assemble the model request as plain dicts: ``{system, messages, tools, tool_choice}``.

    The adapter adds transport/runtime fields (model id, ``anthropic_version``, ``max_tokens``,
    thinking config). ``corrections`` are recent owner mappings used as few-shot guidance
    (empty this slice — rule *creation* is Slice 7); when present they sharpen the merchant→
    category signal without a code change.
    """
    system = _SYSTEM + "\n\n" + _format_categories(categories)
    if corrections:
        system += "\n\n" + _format_corrections(corrections)

    user_content = (
        "Categorize these transactions. Return one result per txnId.\n\n"
        + json.dumps(_txn_views(transactions), ensure_ascii=False)
    )

    return {
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
        "tools": [_result_tool()],
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
    }


def parse_tool_use(tool_input: dict) -> list[dict]:
    """The forced tool call's ``input`` → a normalized ``[{txnId, categoryId, confidence}]``.

    Robust to a model that omits or mistypes fields: a missing/blank ``txnId`` entry is
    dropped, ``categoryId`` is coerced to ``str | None``, ``confidence`` to ``float`` (0.0 on
    junk — :func:`decide_llm` then flags it for review rather than auto-accepting).
    """
    results: list[dict] = []
    for entry in (tool_input or {}).get("categorizations", []) or []:
        if not isinstance(entry, dict):
            continue
        txn_id = entry.get("txnId")
        if not isinstance(txn_id, str) or not txn_id:
            continue
        raw_cat = entry.get("categoryId")
        category_id = raw_cat if isinstance(raw_cat, str) and raw_cat else None
        results.append(
            {"txnId": txn_id, "categoryId": category_id, "confidence": _to_float(entry.get("confidence"))}
        )
    return results


def _txn_views(transactions: list[dict]) -> list[dict]:
    """The minimal per-txn signal the model needs — merchant, raw description, signed amount."""
    return [
        {
            "txnId": t["txnId"],
            "merchant": t.get("merchantNormalized", ""),
            "description": t.get("descriptionRaw", ""),
            "amount": _dollars(t.get("amountCents", 0)),
            "direction": t.get("direction", ""),
        }
        for t in transactions
    ]


def _format_categories(categories: list[dict]) -> str:
    lines = [f"{c['categoryId']} - {c['name']}" for c in categories]
    return "Budget categories (id - name):\n" + "\n".join(lines)


def _format_corrections(corrections: list[dict]) -> str:
    lines = [f"{c.get('merchantNormalized', '')} -> {c.get('categoryName', '')}" for c in corrections]
    return "Known merchant mappings the owner has confirmed before:\n" + "\n".join(lines)


def _result_tool() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Record the category assignment and confidence for each transaction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "categorizations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "txnId": {"type": "string"},
                            "categoryId": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                        },
                        "required": ["txnId", "categoryId", "confidence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["categorizations"],
            "additionalProperties": False,
        },
    }


def _dollars(amount_cents: int) -> str:
    """Cents (signed int) → a human dollar string the model reads naturally, e.g. -42.50."""
    return f"{int(amount_cents) / 100:.2f}"


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
