"""Bedrock adapter — the concrete ``Categorizer`` (ADR-008).

This is the AWS-facing side of the categorization seam: it wraps the pure prompt/parse contract
(``core.categorize.prompt``) in an Amazon Bedrock ``invoke_model`` call to Claude Opus 4.8, and
returns the raw per-transaction results that ``core.categorize.decide_llm`` turns into stored
decisions. Keeping it here (not in ``core/``) preserves the portability seam — ``core/`` has no
AWS imports — and makes the model a swappable config choice (NFR-6.1).

**No new runtime dependency.** We call Bedrock through **boto3** (already the adapters' SDK and
ambient in the Lambda runtime), not the ``anthropic`` package — that keeps the zero-runtime-deps
posture the Lambda asset relies on (no pip/layer step). The request body is the native Anthropic
Messages shape Bedrock expects (``anthropic_version: bedrock-2023-05-31``); structured output is
a **forced tool call**, and thinking is disabled (a fast classification task, and the setting
Bedrock requires alongside a forced ``tool_choice``).

Config is env-driven so the eval harness and a future model swap need no code change:
- ``BEDROCK_MODEL_ID``  — default ``us.anthropic.claude-opus-4-8`` (the Slice-5 baseline). Opus
  4.8 is INFERENCE_PROFILE-only on Bedrock, so this is the *inference-profile* id, not the bare
  foundation-model id. The eval harness points it at ``us.anthropic.claude-sonnet-5`` to A/B.
- ``BEDROCK_MAX_TOKENS`` — output cap for the tool call (default 8192; scales with batch size).
"""
from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config

from core.categorize.prompt import TOOL_NAME, build_request, parse_tool_use

_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-8")
_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "8192"))
_ANTHROPIC_VERSION = "bedrock-2023-05-31"

# Generous client-side retries/backoff over Bedrock throttling; a whole-message retry rides
# above via SQS (architecture §4.6). Read timeout comfortably under the categorizer λ budget.
_client = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=120),
)


class BedrockCategorizer:
    """A ``core.categorize.Categorizer`` backed by Claude Opus 4.8 on Amazon Bedrock."""

    def __init__(self, model_id: str | None = None, *, max_tokens: int | None = None):
        # Args override env (the eval harness passes model_id explicitly to A/B models); env is
        # the deployed default set by CDK.
        self.model_id = model_id or _MODEL_ID
        self.max_tokens = max_tokens or _MAX_TOKENS

    def categorize(
        self,
        transactions: list[dict],
        *,
        categories: list[dict],
        corrections: list[dict],
    ) -> list[dict]:
        if not transactions:
            return []

        req = build_request(transactions, categories=categories, corrections=corrections)
        body = {
            "anthropic_version": _ANTHROPIC_VERSION,
            "max_tokens": self.max_tokens,
            "system": req["system"],
            "messages": req["messages"],
            "tools": req["tools"],
            "tool_choice": req["tool_choice"],
            # Forced tool_choice on Bedrock requires thinking off; a classification task doesn't
            # need it. (An eval-tunable — adaptive thinking is a lever the harness can measure.)
            "thinking": {"type": "disabled"},
        }
        response = _client.invoke_model(modelId=self.model_id, body=json.dumps(body))
        payload = json.loads(response["body"].read())
        return parse_tool_use(_tool_input(payload))


def _tool_input(payload: dict) -> dict:
    """Pull the forced tool call's ``input`` out of the Anthropic Messages response content."""
    for block in payload.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
            return block.get("input", {})
    return {}
