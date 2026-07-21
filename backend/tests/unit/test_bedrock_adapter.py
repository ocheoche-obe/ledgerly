"""Unit tests for the Bedrock categorizer adapter (adapters/bedrock.py).

Bedrock isn't mockable with moto, so we stub the module-level boto3 client and assert the two
things the adapter owns: the request body it sends (forced tool, model id, native Anthropic
envelope) and how it parses the forced tool_use response back into raw results. The prompt
*content* is tested in test_categorize.py; here we only verify the transport wrapping.
"""
from __future__ import annotations

import importlib
import json
import sys

import pytest


@pytest.fixture
def bedrock(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8")
    sys.modules.pop("adapters.bedrock", None)
    module = importlib.import_module("adapters.bedrock")
    return module


class _FakeBody:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _stub_invoke(monkeypatch, module, payload, captured):
    def fake_invoke_model(*, modelId, body):
        captured["modelId"] = modelId
        captured["body"] = json.loads(body)
        return {"body": _FakeBody(payload)}

    monkeypatch.setattr(module._client, "invoke_model", fake_invoke_model)


CATEGORIES = [{"categoryId": "01CATFOOD", "name": "Groceries"}]
TXNS = [{"txnId": "aaa", "merchantNormalized": "trader joes", "descriptionRaw": "TRADER JOES",
         "amountCents": -4210, "direction": "debit"}]


def test_empty_batch_short_circuits_without_calling_bedrock(bedrock, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(bedrock._client, "invoke_model",
                        lambda **kw: called.__setitem__("n", called["n"] + 1))
    assert bedrock.BedrockCategorizer().categorize([], categories=CATEGORIES, corrections=[]) == []
    assert called["n"] == 0


def test_request_body_forces_the_tool_and_targets_the_model(bedrock, monkeypatch):
    captured: dict = {}
    payload = {"content": [{"type": "tool_use", "name": "record_categorizations",
                            "input": {"categorizations": [
                                {"txnId": "aaa", "categoryId": "01CATFOOD", "confidence": 0.9}]}}]}
    _stub_invoke(monkeypatch, bedrock, payload, captured)

    results = bedrock.BedrockCategorizer().categorize(TXNS, categories=CATEGORIES, corrections=[])

    assert captured["modelId"] == "anthropic.claude-opus-4-8"
    body = captured["body"]
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["tool_choice"] == {"type": "tool", "name": "record_categorizations"}
    assert body["thinking"] == {"type": "disabled"}
    assert results == [{"txnId": "aaa", "categoryId": "01CATFOOD", "confidence": 0.9}]


def test_model_id_override_wins_over_env(bedrock, monkeypatch):
    # The eval harness passes model_id explicitly to A/B Opus vs Sonnet.
    captured: dict = {}
    _stub_invoke(monkeypatch, bedrock, {"content": []}, captured)
    bedrock.BedrockCategorizer(model_id="anthropic.claude-sonnet-5").categorize(
        TXNS, categories=CATEGORIES, corrections=[])
    assert captured["modelId"] == "anthropic.claude-sonnet-5"


def test_missing_tool_block_parses_to_empty(bedrock, monkeypatch):
    captured: dict = {}
    _stub_invoke(monkeypatch, bedrock, {"content": [{"type": "text", "text": "no tool"}]}, captured)
    assert bedrock.BedrockCategorizer().categorize(TXNS, categories=CATEGORIES, corrections=[]) == []
