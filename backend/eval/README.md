# Categorization eval harness (Slice 5, NFR-5.3)

The measurement gate for AI categorization: accuracy is a **number**, not a vibe. It scores the
categorizer's predictions against the owner's ground truth, and A/Bs models so the Opus 4.8 vs
Sonnet 5 choice (plan, Slice 5) is decided on data.

## Layout

- `harness.py` — pure scoring logic (predict via the production `decide_llm` rules → score vs
  truth). Unit-tested with a fake model in `tests/unit/test_eval.py`; no Bedrock in CI.
- `run.py` — CLI. Calls **live Bedrock**, so run it with the Ledgerly profile.
- `samples/labeled_set.example.json` — synthetic template showing the file format.

## The "you draft, I confirm" flow (owner-agreed)

Labeling with the same model we're grading is mildly circular, so the owner's corrections are
what make the set ground truth. The harness surfaces every draft for review — only the corrected
set counts as the baseline.

```bash
cd backend

# 1. Draft labels over an unlabeled set (owner reviews/corrects the output)
AWS_PROFILE=ledgerly-dev AWS_REGION=us-east-1 \
  python -m eval.run label --set eval/samples/my_set.json

# 2. …owner edits my_set.drafted.json: fix any wrong trueCategoryId, delete the _draft* fields…

# 3. Score the corrected set across both models
AWS_PROFILE=ledgerly-dev AWS_REGION=us-east-1 \
  python -m eval.run score --set eval/samples/my_set.drafted.json \
    --models us.anthropic.claude-opus-4-8 us.anthropic.claude-sonnet-5
```

Model ids are Bedrock **inference-profile** ids (`us.…`) — Opus 4.8 and Sonnet 5 are
INFERENCE_PROFILE-only, so the bare foundation-model id won't invoke.

`score` prints accuracy, correct/total, review-rate, and uncategorized-count per model. Baseline
stays Opus 4.8 (ADR-008); if Sonnet 5 matches within noise, that justifies a downgrade + a
superseding ADL note (plan, Slice 5). `--threshold` overrides the 0.8 default to see how the
auto-accept vs review split moves.

## Set format

```jsonc
{
  "categories": [{ "categoryId": "…", "name": "…" }],
  "transactions": [
    { "txnId": "…", "merchantNormalized": "…", "descriptionRaw": "…",
      "amountCents": -6231, "direction": "debit", "trueCategoryId": "…" }
  ]
}
```

Real sets are the owner's data — keep them anonymized-enough and out of anything shared. The
committed sample is synthetic.
