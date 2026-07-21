"""Categorization eval CLI (NFR-5.3) — run manually against live Bedrock.

The measurement gate for Slice 5's success criterion 2 (≥80% accuracy) and the A/B that turns
"which model?" into data (plan, Slice 5). Not a Lambda — a developer script; it calls Bedrock,
so run it with the Ledgerly profile:

    AWS_PROFILE=ledgerly-dev AWS_REGION=us-east-1 python -m eval.run score \\
        --set eval/samples/labeled_set.example.json \\
        --models us.anthropic.claude-opus-4-8 us.anthropic.claude-sonnet-5

Model ids are Bedrock *inference-profile* ids (Opus 4.8 / Sonnet 5 are INFERENCE_PROFILE-only).

Two subcommands implement the agreed "you draft, I confirm" labeling flow (plan, Slice 5):

  label  — run the baseline model over an *unlabeled* set and write a draft-labeled copy for
           the owner to review/correct. The drafts are suggestions, not ground truth; the
           corrected file is what makes the baseline trustworthy.
  score  — run one or more models over a *corrected* labeled set and print accuracy per model.

The set is JSON: ``{"categories": [{categoryId, name}], "transactions": [{txnId,
merchantNormalized, descriptionRaw, amountCents, direction, trueCategoryId?}]}``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.categorize import DEFAULT_CONFIDENCE_THRESHOLD
from eval.harness import evaluate, predict

_BASELINE_MODEL = "us.anthropic.claude-opus-4-8"


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "categories" not in data or "transactions" not in data:
        raise SystemExit(f"{path}: expected keys 'categories' and 'transactions'")
    return data


def _categorizer(model_id: str):
    # Imported here so `--help` and the pure harness tests don't require boto3 / AWS creds.
    from adapters.bedrock import BedrockCategorizer

    return BedrockCategorizer(model_id=model_id)


def cmd_score(args: argparse.Namespace) -> int:
    data = _load(args.set)
    categories = data["categories"]
    transactions = data["transactions"]
    truth = {t["txnId"]: t["trueCategoryId"] for t in transactions if t.get("trueCategoryId")}
    if not truth:
        raise SystemExit(f"{args.set}: no labeled transactions (set 'trueCategoryId' first — "
                         f"use the `label` command to draft, then correct)")

    print(f"Scoring {len(truth)} labeled transactions (threshold {args.threshold})\n")
    print(f"{'model':<32} {'acc':>7} {'correct':>9} {'review':>8} {'uncat':>7}")
    print("-" * 68)
    for model in args.models:
        result = evaluate(_categorizer(model), model, transactions, categories, truth,
                         threshold=args.threshold)
        print(f"{model:<32} {result.accuracy:>6.1%} {result.correct:>4}/{result.total:<4} "
              f"{result.review_rate:>7.1%} {result.uncategorized:>7}")
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    data = _load(args.set)
    categories = data["categories"]
    transactions = data["transactions"]

    decisions = predict(_categorizer(args.model), transactions, categories,
                       threshold=args.threshold)
    names = {c["categoryId"]: c["name"] for c in categories}
    for txn in transactions:
        d = decisions[txn["txnId"]]
        # Draft the label for the owner to confirm/correct — mark it clearly as a draft.
        txn["trueCategoryId"] = d.category_id
        txn["_draft"] = True
        txn["_draftCategoryName"] = names.get(d.category_id, "(uncategorized)")
        txn["_draftConfidence"] = round(d.confidence, 3)

    out = args.out or args.set.replace(".json", ".drafted.json")
    Path(out).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(transactions)} draft labels → {out}\n"
          f"Review each trueCategoryId, fix any that are wrong, then remove the _draft* fields "
          f"and run `score`.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run", description=__doc__)
    parser.add_argument("--threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD,
                       help=f"confidence threshold (default {DEFAULT_CONFIDENCE_THRESHOLD})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="score model(s) against a labeled set")
    p_score.add_argument("--set", required=True, help="path to the labeled JSON set")
    p_score.add_argument("--models", nargs="+",
                        default=[_BASELINE_MODEL, "us.anthropic.claude-sonnet-5"],
                        help="Bedrock inference-profile ids to A/B (default: Opus 4.8 + Sonnet 5)")
    p_score.set_defaults(func=cmd_score)

    p_label = sub.add_parser("label", help="draft labels for the owner to confirm")
    p_label.add_argument("--set", required=True, help="path to the unlabeled JSON set")
    p_label.add_argument("--model", default=_BASELINE_MODEL, help="model to draft with")
    p_label.add_argument("--out", help="output path (default: <set>.drafted.json)")
    p_label.set_defaults(func=cmd_label)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
