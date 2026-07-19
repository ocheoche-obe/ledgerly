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
from core.imports import import_view, new_import
from core.settings import default_profile, settings_view
from core.transactions import txn_sk, txn_view

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


def _import_sk(import_id: str) -> str:
    return f"IMPORT#{import_id}"


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


# --- imports & transactions (Slice 4, FR-2) --------------------------------------------

# Cap how many per-row errors we persist on the import record: counts are authoritative
# (FR-2.5), a sample of errors is enough for the owner, and it keeps the item well under
# DynamoDB's 400 KB limit on a pathological all-bad file.
_MAX_STORED_ERRORS = 50


def create_import(
    sub: str, import_id: str, *, filename: str, account_label: str, account_id: str,
    object_key: str, created_at: str,
) -> dict:
    """AP 11 (write) — record a pending import before the file is uploaded.

    The item is created here so the UI can immediately poll it (AP 11); the import Lambda
    advances it once the S3 upload fires. `import_id` is generated by the caller (a ULID) so
    the S3 object key and the DynamoDB record share one id.
    """
    item = {
        "pk": _pk(sub),
        "sk": _import_sk(import_id),
        "objectKey": object_key,
        **new_import(
            import_id, filename=filename, account_label=account_label,
            account_id=account_id, created_at=created_at,
        ),
    }
    _table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    return import_view(item)


def get_import(sub: str, import_id: str) -> dict | None:
    """AP 11 (read) — fetch one import for status polling. None if it doesn't exist."""
    item = _table.get_item(Key={"pk": _pk(sub), "sk": _import_sk(import_id)}).get("Item")
    return import_view(item) if item else None


def get_import_raw(sub: str, import_id: str) -> dict | None:
    """The stored import item (with key/internal attributes) — for the import Lambda."""
    return _table.get_item(Key={"pk": _pk(sub), "sk": _import_sk(import_id)}).get("Item")


def list_imports(sub: str, limit: int = 20) -> list[dict]:
    """AP 11 — recent imports, newest first (ULID sort key + reverse scan)."""
    items = _table.query(
        KeyConditionExpression=Key("pk").eq(_pk(sub)) & Key("sk").begins_with("IMPORT#"),
        ScanIndexForward=False,
        Limit=limit,
    ).get("Items", [])
    return [import_view(i) for i in items]


def set_import_status(
    sub: str, import_id: str, status: str, *,
    added: int | None = None, duplicate: int | None = None, failed: int | None = None,
    errors: list[dict] | None = None,
) -> None:
    """AP 11 (write) — advance an import's status and (when finishing) its counts.

    `status` is a DynamoDB reserved word, so it goes through an expression-attribute name.
    """
    assignments = ["#status = :status"]
    values: dict[str, object] = {":status": status}
    for field, val in (("added", added), ("duplicate", duplicate), ("failed", failed)):
        if val is not None:
            assignments.append(f"{field} = :{field}")
            values[f":{field}"] = val
    if errors is not None:
        assignments.append("errors = :errors")
        values[":errors"] = errors[:_MAX_STORED_ERRORS]

    _table.update_item(
        Key={"pk": _pk(sub), "sk": _import_sk(import_id)},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=values,
    )


def claim_file(sub: str, file_hash: str, import_id: str) -> bool:
    """AP 12 — file-level idempotency (FR-2.2). True if this import may proceed; False if
    the exact file was already imported under a *different* import.

    The claim is a conditional put on `FILEHASH#<sha256>` recording the claiming importId.
    If the put loses (the hash exists), we compare owners: the same importId means the import
    Lambda is re-running after a crash/redelivery (architecture §3.1) — return True so it
    resumes (the transaction conditional puts make the replay harmless); a different importId
    is a genuine re-upload — return False.
    """
    try:
        _table.put_item(
            Item={
                "pk": _pk(sub),
                "sk": f"FILEHASH#{file_hash}",
                "type": "FILEHASH",
                "importId": import_id,
            },
            ConditionExpression="attribute_not_exists(sk)",
        )
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        existing = _table.get_item(
            Key={"pk": _pk(sub), "sk": f"FILEHASH#{file_hash}"}
        ).get("Item", {})
        return existing.get("importId") == import_id  # our own prior claim → resume


def put_transaction(sub: str, item_body: dict) -> bool:
    """AP 7 — row-level idempotency (FR-2.2). True if the transaction was added; False if it
    already existed (a re-import or overlapping export). Dedupe is key-equality on the
    natural key baked into `sk` (ADR-012).
    """
    item = {"pk": _pk(sub), "sk": txn_sk(item_body["date"], item_body["txnId"]), **item_body}
    try:
        _table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # already imported
        raise


def query_transactions(sub: str, *, date_from: str, date_to: str, limit: int = 500) -> list[dict]:
    """AP 6 — transactions in an inclusive date window, oldest first (`TXN#<date>#…`).

    The upper bound uses `TXN#<date_to>~`: '~' sorts after '#' and every digit, so the whole
    of `date_to` is captured regardless of the txnId suffix.

    Single-page (`Limit`) — enough for the basic list at slice-4 window sizes (a couple of
    months ≈ a few hundred items). Pagination for wide ranges lands with filters/search in
    Slice 7; until then callers should keep windows within a cycle or two.
    """
    items = _table.query(
        KeyConditionExpression=Key("pk").eq(_pk(sub))
        & Key("sk").between(f"TXN#{date_from}", f"TXN#{date_to}~"),
        Limit=limit,
    ).get("Items", [])
    return [txn_view(i) for i in items]
