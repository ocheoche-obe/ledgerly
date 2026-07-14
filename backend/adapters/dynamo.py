"""DynamoDB persistence adapters (boto3).

This is the AWS-facing seam. `core/` stays free of AWS imports so it can be unit-tested in
isolation; the boto3 dependency is quarantined here. Keys follow architecture §2.4:
every item is `pk = USER#<sub>`; settings live at `sk = PROFILE`.
"""
from __future__ import annotations

import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.settings import default_profile, settings_view

_TABLE_NAME = os.environ["TABLE_NAME"]
_dynamodb = boto3.resource(
    "dynamodb",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)
_table = _dynamodb.Table(_TABLE_NAME)


def _pk(sub: str) -> str:
    return f"USER#{sub}"


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
