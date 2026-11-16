"""Delete Plaid Sandbox rows from one user's partition — owner-run, dry run by default.

Owner decision 2026-11-15 (Slice 9): Sandbox data belongs to a separate Cognito test user;
the Sandbox rows already written under the owner's own partition are removed. What counts as
a Sandbox row is decided by ``core.plaid_purge.plan_sandbox_purge`` (unit-tested); this
script only reads the partition, prints that plan, and — when told to, with the exact count
it printed — deletes those keys.

Safeguards, in order:
  1. The caller must be in the Ledgerly account (ADR-010), via the ``ledgerly-dev`` profile.
  2. The table must be the dev table (``--table`` is checked against the stage name).
  3. Any still-linked Plaid connection blocks the run: disconnect it in the app first.
  4. Without ``--execute`` nothing is written. With it, ``--expect`` must equal the total
     the dry run printed, so a delete never runs on a selection nobody looked at.
  5. Before deleting, every selected item is written to a local JSON manifest. The table
     also has point-in-time recovery (35 days), which is the real undo.

    AWS_PROFILE=ledgerly-dev python -m ops.purge_plaid_sandbox --sub <cognito-sub>
    AWS_PROFILE=ledgerly-dev python -m ops.purge_plaid_sandbox --sub <sub> --execute --expect N

Run from ``backend/``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

from core.plaid_purge import PurgeBlockedError, plan_sandbox_purge

LEDGERLY_ACCOUNT = "816020558700"
DEFAULT_TABLE = "ledgerly-dev"


def _read_partition(table, sub: str) -> list[dict]:
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{sub}")}
    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sub", required=True, help="Cognito sub whose partition to purge")
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--execute", action="store_true", help="actually delete")
    parser.add_argument("--expect", type=int, help="total from the dry run (required to execute)")
    parser.add_argument("--manifest-dir", default=".", help="where the pre-delete manifest goes")
    args = parser.parse_args(argv)

    account = boto3.client("sts").get_caller_identity()["Account"]
    if account != LEDGERLY_ACCOUNT:
        print(f"REFUSED: credentials are for account {account}, not Ledgerly "
              f"({LEDGERLY_ACCOUNT}). Use AWS_PROFILE=ledgerly-dev.")
        return 2
    if not args.table.endswith("-dev"):
        print(f"REFUSED: {args.table} is not a dev table; Plaid Sandbox data only exists in dev.")
        return 2

    table = boto3.resource("dynamodb").Table(args.table)
    items = _read_partition(table, args.sub)
    try:
        plan = plan_sandbox_purge(items)
    except PurgeBlockedError as err:
        print(f"BLOCKED: {err}")
        return 3

    summary = plan.summary()
    print(json.dumps({"table": args.table, "sub": args.sub, "partitionItems": len(items),
                      **summary}, indent=2))
    if plan.left_alone:
        print("Left alone (Plaid-looking but not provably Sandbox):")
        for sk in plan.left_alone:
            print(f"  {sk}")

    if not args.execute:
        print(f"\nDry run: nothing deleted. To delete these {summary['total']} items, re-run "
              f"with --execute --expect {summary['total']}")
        return 0
    if args.expect != summary["total"]:
        print(f"REFUSED: --expect {args.expect} but the selection is now {summary['total']}. "
              "Re-run the dry run and review it.")
        return 2
    if not plan.keys:
        print("Nothing to delete.")
        return 0

    selected = set(plan.keys)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest = Path(args.manifest_dir) / f"plaid-sandbox-purge-{stamp}.json"
    manifest.write_text(json.dumps(
        [i for i in items if i["sk"] in selected], default=str, indent=1))
    print(f"Manifest of the {len(selected)} items written to {manifest}")

    with table.batch_writer() as batch:  # chunks of 25 and retries unprocessed items itself
        for sk in plan.keys:
            batch.delete_item(Key={"pk": f"USER#{args.sub}", "sk": sk})

    remaining = plan_sandbox_purge(_read_partition(table, args.sub))
    print(f"Deleted {len(selected)} items. Sandbox items still selected afterwards: "
          f"{remaining.summary()['total']}")
    return 0 if not remaining.keys else 1


if __name__ == "__main__":
    sys.exit(main())
