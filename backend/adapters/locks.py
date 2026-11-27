"""A short-lived mutual-exclusion lease in the app's DynamoDB table (ADR-016, backlog B-11).

Secrets Manager has no compare-and-swap, so two writers doing read-modify-write on the
Plaid access-token document could each drop the other's change (connect one bank while
disconnecting another). Writers take this lease around the read-modify-write instead.

The lease is one item, ``pk = LOCK#<name>``, ``sk = LOCK``. It is not a user's item, so it
sits outside every ``USER#<sub>`` partition by design: the document it guards is shared by
all users. A holder that crashes leaves an item behind; its ``expiresAt`` lets the next
writer take over once the lease has run out, so nothing ever waits for a human.
"""
from __future__ import annotations

import os
import secrets as _random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_client = None


def _dynamo():
    global _client
    if _client is None:
        _client = boto3.client("dynamodb", config=Config(retries={"max_attempts": 3,
                                                                    "mode": "standard"}))
    return _client


class LockBusy(RuntimeError):
    """Someone else held the lease for the whole wait. Safe to retry later."""


def _key(name: str) -> dict:
    return {"pk": {"S": f"LOCK#{name}"}, "sk": {"S": "LOCK"}}


def try_acquire(name: str, owner: str, *, lease_seconds: int, now: float) -> bool:
    """Take the lease if it is free or expired. True if this owner now holds it."""
    try:
        _dynamo().put_item(
            TableName=os.environ["TABLE_NAME"],
            Item={**_key(name), "owner": {"S": owner},
                  "expiresAt": {"N": str(int(now) + lease_seconds)}},
            ConditionExpression="attribute_not_exists(pk) OR expiresAt < :now",
            ExpressionAttributeValues={":now": {"N": str(int(now))}},
        )
        return True
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def release(name: str, owner: str) -> None:
    """Give the lease back, only if this owner still holds it (an expired lease taken over by
    someone else is theirs now)."""
    try:
        _dynamo().delete_item(
            TableName=os.environ["TABLE_NAME"],
            Key=_key(name),
            ConditionExpression="#o = :owner",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={":owner": {"S": owner}},
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


@contextmanager
def held(
    name: str,
    *,
    lease_seconds: int = 20,
    wait_seconds: float = 6.0,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[None]:
    """Run the block while holding the lease. Raises :class:`LockBusy` if it stays taken for
    ``wait_seconds``. The lease outlives the block's expected runtime (two Secrets Manager
    calls) by a wide margin, and is shorter than the API Lambda's timeout."""
    owner = _random.token_hex(8)
    deadline = clock() + wait_seconds
    while not try_acquire(name, owner, lease_seconds=lease_seconds, now=clock()):
        if clock() >= deadline:
            raise LockBusy(f"the {name} lock is busy")
        sleep(0.2)
    try:
        yield
    finally:
        release(name, owner)
