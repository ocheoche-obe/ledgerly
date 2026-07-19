"""DynamoDB persistence adapters (boto3).

This is the AWS-facing seam. `core/` stays free of AWS imports so it can be unit-tested in
isolation; the boto3 dependency is quarantined here. Keys follow architecture §2.4:
every item is `pk = USER#<sub>`; settings live at `sk = PROFILE`.
"""
from __future__ import annotations

import os
from datetime import date

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from core.categories import (
    category_view,
    clean_name,
    new_category,
    starter_categories,
    validate_status,
)
from core.cycles import plan_cadence_change
from core.settings import default_profile, settings_view

_TABLE_NAME = os.environ["TABLE_NAME"]
_dynamodb = boto3.resource(
    "dynamodb",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)
_table = _dynamodb.Table(_TABLE_NAME)


def _pk(sub: str) -> str:
    return f"USER#{sub}"


def _cat_sk(category_id: str) -> str:
    return f"CAT#{category_id}"


def get_or_create_settings(sub: str) -> dict:
    """AP #1 — GetItem PROFILE, creating the default on first login.

    Idempotent: the create is a conditional put, so a concurrent first-login race resolves
    to a single profile (the loser re-reads the winner's item).
    """
    key = {"pk": _pk(sub), "sk": "PROFILE"}

    existing = _table.get_item(Key=key).get("Item")
    if existing:
        return settings_view(existing)

    item = {**key, **default_profile()}
    try:
        _table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return settings_view(item)
    except ClientError as err:
        if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Lost the race — return whatever the winner wrote.
        winner = _table.get_item(Key=key).get("Item", item)
        return settings_view(winner)


def update_cadence(sub: str, *, kind: str, anchor: str | None = None) -> dict:
    """AP #1 (write) — apply a cadence change to the PROFILE (FR-4.2).

    The change is planned in pure core (`plan_cadence_change`): it takes effect from the next
    cycle and never rewrites past cycles. We read the current cadences, compute the new list,
    and persist it. `anchor` is an ISO date string (required for biweekly).
    """
    key = {"pk": _pk(sub), "sk": "PROFILE"}
    profile = _table.get_item(Key=key).get("Item")
    if not profile:  # ensure the PROFILE exists before mutating it
        get_or_create_settings(sub)
        profile = _table.get_item(Key=key).get("Item")

    anchor_date = date.fromisoformat(anchor) if anchor else None
    new_cadences = plan_cadence_change(
        profile["cadences"], kind=kind, anchor=anchor_date, today=date.today()
    )
    updated = _table.update_item(
        Key=key,
        UpdateExpression="SET cadences = :c",
        ExpressionAttributeValues={":c": new_cadences},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    return settings_view(updated)


def _ensure_starter_categories(sub: str) -> None:
    """Seed the starter category set once, on first run (FR-4.4).

    Ordering matters for durability: we write the starters *first*, then flip the
    `startersSeeded` flag. If the Lambda dies mid-seed, the flag stays unset and the next
    load simply retries — a recoverable duplicate at worst, never a permanent empty list.
    (The reverse order would strand the owner with no categories after a crash.) The
    `attribute_not_exists` guard on the flag stops steady-state re-seeding once it succeeds;
    a concurrent first-load double-seed is a non-issue for a single-user app and only ever
    costs a cosmetic duplicate.
    """
    get_or_create_settings(sub)  # PROFILE must exist to carry the flag
    key = {"pk": _pk(sub), "sk": "PROFILE"}
    if _table.get_item(Key=key).get("Item", {}).get("startersSeeded"):
        return  # already seeded

    with _table.batch_writer() as batch:
        for cat in starter_categories():
            batch.put_item(Item={"pk": _pk(sub), "sk": _cat_sk(cat["categoryId"]), **cat})

    _table.update_item(
        Key=key,
        UpdateExpression="SET startersSeeded = :t",
        ExpressionAttributeValues={":t": True},
    )


def list_categories(sub: str) -> list[dict]:
    """AP #2 — list all categories (active + archived), seeding starters on first run."""
    _ensure_starter_categories(sub)
    items = _table.query(
        KeyConditionExpression=Key("pk").eq(_pk(sub)) & Key("sk").begins_with("CAT#")
    ).get("Items", [])
    views = [category_view(i) for i in items]
    return sorted(views, key=lambda c: (c["sortOrder"], c["name"]))


def create_category(sub: str, name: str) -> dict:
    """AP #3 (create) — add a category at the end of the sort order (FR-4.1)."""
    existing = _table.query(
        KeyConditionExpression=Key("pk").eq(_pk(sub)) & Key("sk").begins_with("CAT#"),
        ProjectionExpression="sortOrder",
    ).get("Items", [])
    next_order = max((int(i.get("sortOrder", 0)) for i in existing), default=-1) + 1

    cat = new_category(name, sort_order=next_order)  # validates the name (raises ValueError)
    item = {"pk": _pk(sub), "sk": _cat_sk(cat["categoryId"]), **cat}
    _table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    return category_view(item)


def update_category(
    sub: str, category_id: str, *, name: str | None = None, status: str | None = None
) -> dict | None:
    """AP #3 (rename/archive) — update a category in place (FR-4.1).

    Returns the updated view, or None if the category doesn't exist. Archiving only flips
    the status this slice; transaction reassignment (FR-4.5) is wired in Slice 7.
    """
    sets: dict[str, object] = {}
    if name is not None:
        sets["name"] = clean_name(name)
    if status is not None:
        sets["status"] = validate_status(status)
    if not sets:
        raise ValueError("nothing to update: provide name and/or status")

    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in sets)
    try:
        updated = _table.update_item(
            Key={"pk": _pk(sub), "sk": _cat_sk(category_id)},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(sk)",
            ExpressionAttributeNames={f"#{k}": k for k in sets},
            ExpressionAttributeValues={f":{k}": v for k, v in sets.items()},
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None  # no such category
        raise
    return category_view(updated)
