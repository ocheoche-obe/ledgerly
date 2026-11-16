"""Plaid API adapter (ADR-014) — stdlib ``urllib``, no SDK.

Ledgerly's Lambda asset has no ``pip`` step, and this integration needs a handful of JSON
POSTs, so the calls are made directly. Request and response field names were checked against
Plaid's published API reference when this was written (2026-11-15), not recalled.

Rules this module enforces, because they are the ones that are expensive to get wrong:

- **Sandbox only.** The base URL comes from ``PLAID_ENV`` and the only accepted value is
  ``sandbox``. Reaching Plaid Production is a separate decision (a follow-up ADR), so it is
  not merely unconfigured here — it is refused.
- **Keys travel in headers** (``PLAID-CLIENT-ID`` / ``PLAID-SECRET``), never in a request
  body, so no body this module builds ever contains them.
- **Nothing sensitive is logged or raised.** :class:`PlaidError` carries Plaid's
  ``error_type``, ``error_code`` and ``request_id`` (the handle Plaid support needs) and
  nothing else: not the request, not the response body, not a token.
- **Errors are branched on ``error_code`` / ``error_type``**, never on HTTP status or message
  text (Plaid returns HTTP 400 for some transient institution errors).
"""
from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from decimal import Decimal

from core.plaid_sync import MUTATION_DURING_PAGINATION, PAGE_SIZE

logger = logging.getLogger()

_BASE_URLS = {"sandbox": "https://sandbox.plaid.com"}

# Pins request/response shapes to the API version this code was written against.
_PLAID_VERSION = "2020-09-14"

# The first sync after a history backfill can be several times slower than a normal call.
_TIMEOUT_SECONDS = 60

_MAX_ATTEMPTS = 3
_RETRYABLE_CODES = frozenset({"INSTITUTION_DOWN", "INSTITUTION_NOT_RESPONDING"})
_RETRYABLE_TYPES = frozenset({"RATE_LIMIT_EXCEEDED"})


class PlaidConfigError(ValueError):
    """This deployment's Plaid configuration is unusable (e.g. an unsupported ``PLAID_ENV``).
    A server-side fault, never something the caller sent."""


class PlaidError(Exception):
    """A Plaid API failure, reduced to what is safe to log and useful to act on."""

    def __init__(self, *, error_type: str, error_code: str, request_id: str, status: int,
                 endpoint: str):
        super().__init__(f"Plaid {endpoint} failed: {error_type}/{error_code}")
        self.error_type = error_type
        self.error_code = error_code
        self.request_id = request_id
        self.status = status
        self.endpoint = endpoint

    def log_fields(self) -> dict:
        return {
            "plaidEndpoint": self.endpoint,
            "plaidErrorType": self.error_type,
            "plaidErrorCode": self.error_code,
            "plaidRequestId": self.request_id,
            "httpStatus": self.status,
        }

    @property
    def retryable(self) -> bool:
        return (
            self.error_code in _RETRYABLE_CODES
            or self.error_type in _RETRYABLE_TYPES
            or self.status >= 500
        )


def is_mutation_during_pagination(err: Exception) -> bool:
    return isinstance(err, PlaidError) and err.error_code == MUTATION_DURING_PAGINATION


def base_url(plaid_env: str) -> str:
    """The API host for an environment. Only ``sandbox`` is allowed in this slice."""
    try:
        return _BASE_URLS[plaid_env]
    except KeyError:
        raise PlaidConfigError(
            "PLAID_ENV must be 'sandbox' - no other Plaid environment is enabled (ADR-014)"
        ) from None


def _default_transport(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    """POST and return ``(status, body)``; an HTTP error status is a normal return here."""
    try:
        # The URL is always one of the fixed https hosts in _BASE_URLS, never caller-supplied.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


class PlaidClient:
    """The Plaid calls Ledgerly makes. ``credentials`` is a callable returning
    ``(client_id, secret)`` so the keys are fetched lazily and never held by callers.
    """

    def __init__(
        self,
        *,
        plaid_env: str,
        credentials: Callable[[], tuple[str, str]],
        transport: Callable[[urllib.request.Request, float], tuple[int, bytes]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = _TIMEOUT_SECONDS,
        max_attempts: int = _MAX_ATTEMPTS,
    ):
        self.plaid_env = plaid_env
        self._base_url = base_url(plaid_env)
        self._credentials = credentials
        self._transport = transport or _default_transport
        self._sleep = sleep
        self._timeout = timeout
        self._max_attempts = max_attempts

    # --- Link ---------------------------------------------------------------------------

    def link_token_create(self, *, client_user_id: str, access_token: str | None = None) -> dict:
        """``/link/token/create`` → ``{link_token, expiration, request_id}``.

        ``transactions`` is the only required product, so no institution is filtered out of
        Link for lacking anything else. ``identity`` is consented but not requested, fetched
        or billed, so account-ownership checks can be added later without sending the owner
        back through Link.

        **Update mode** (``access_token`` given): re-opens Link on an *existing* Item to repair
        a broken login. No products are sent — the Item already has them, and listing products
        in update mode asks for additional consent instead of a repair. Link then returns no
        new public token, so nothing is exchanged afterwards and the access token is unchanged.
        An update-mode token lives 30 minutes rather than 4 hours.
        """
        body: dict = {
            "client_name": "Ledgerly",
            "language": "en",
            "country_codes": ["US"],
            "user": {"client_user_id": client_user_id},
        }
        if access_token:
            body["access_token"] = access_token
        else:
            body["products"] = ["transactions"]
            body["additional_consented_products"] = ["identity"]
        return self._post("/link/token/create", body)

    def item_remove(self, *, access_token: str) -> dict:
        """``/item/remove`` → ``{request_id}``. Ends the Item at Plaid: the access token stops
        working and billing for it stops. Deleting only Ledgerly's own record would leave the
        connection live (and, in Production, billed)."""
        return self._post("/item/remove", {"access_token": access_token})

    def item_public_token_exchange(self, *, public_token: str) -> dict:
        """``/item/public_token/exchange`` → ``{access_token, item_id, request_id}``.

        The caller must store the access token server-side and never return or log it.

        **Sent exactly once, never retried.** A public token is single-use. If the first
        attempt reached Plaid but its response was lost, a second attempt would be refused
        and look like a plain failure while a live connection existed with no token on our
        side. One attempt keeps the outcome unambiguous: either a token came back or the
        owner links again.
        """
        return self._post("/item/public_token/exchange", {"public_token": public_token},
                          max_attempts=1)

    # --- Data ---------------------------------------------------------------------------

    def accounts_get(self, *, access_token: str) -> dict:
        """``/accounts/get`` → ``{accounts, item, request_id}`` — the authoritative account
        list, with Plaid's cached balances (free; not the real-time Balance product)."""
        return self._post("/accounts/get", {"access_token": access_token})

    def transactions_sync(self, *, access_token: str, cursor: str) -> dict:
        """One page of ``/transactions/sync``. An empty cursor asks for full history."""
        body: dict = {
            "access_token": access_token,
            "count": PAGE_SIZE,
            "options": {"include_original_description": True},
        }
        if cursor:
            body["cursor"] = cursor
        return self._post("/transactions/sync", body)

    # --- Sandbox test helpers (these endpoints do not exist outside Sandbox) -------------

    def sandbox_public_token_create(self, *, institution_id: str, username: str,
                                    password: str) -> dict:
        """``/sandbox/public_token/create`` — links a Sandbox test user without the Link UI."""
        return self._post("/sandbox/public_token/create", {
            "institution_id": institution_id,
            "initial_products": ["transactions"],
            "options": {"override_username": username, "override_password": password},
        })

    def sandbox_item_reset_login(self, *, access_token: str) -> dict:
        """``/sandbox/item/reset_login`` — puts a Sandbox Item into ``ITEM_LOGIN_REQUIRED`` so
        the reconnect (update mode) path can be exercised end to end."""
        return self._post("/sandbox/item/reset_login", {"access_token": access_token})

    def transactions_refresh(self, *, access_token: str) -> dict:
        """``/transactions/refresh`` — in Sandbox, makes the dynamic test user generate new
        activity. In Production this is a separately billed add-on; nothing in Ledgerly's
        owner-facing paths calls it."""
        return self._post("/transactions/refresh", {"access_token": access_token})

    # --- transport ----------------------------------------------------------------------

    def _post(self, endpoint: str, body: dict, *, max_attempts: int | None = None) -> dict:
        max_attempts = self._max_attempts if max_attempts is None else max_attempts
        client_id, secret = self._credentials()
        request = urllib.request.Request(
            self._base_url + endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "PLAID-CLIENT-ID": client_id,
                "PLAID-SECRET": secret,
                "Plaid-Version": _PLAID_VERSION,
            },
        )

        attempt = 0
        while True:
            attempt += 1
            error = self._attempt(request, endpoint)
            if not isinstance(error, PlaidError):
                return error  # the parsed success response
            if not error.retryable or attempt >= max_attempts:
                logger.warning(json.dumps({"stage": "plaid", "attempt": attempt,
                                           **error.log_fields()}))
                raise error
            # Capped exponential backoff with jitter.
            self._sleep(min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.25))

    def _attempt(self, request: urllib.request.Request, endpoint: str) -> dict | PlaidError:
        try:
            status, raw = self._transport(request, self._timeout)
        except (urllib.error.URLError, TimeoutError):
            # Network failure: no response to quote. Deliberately not chained or logged with
            # its arguments — a URLError's repr can include the request.
            return PlaidError(error_type="NETWORK_ERROR", error_code="NETWORK_ERROR",
                              request_id="", status=599, endpoint=endpoint)
        try:
            # Decimal, not float: amounts become exact cents, and DynamoDB rejects floats.
            parsed = json.loads(raw, parse_float=Decimal)
        except (ValueError, UnicodeDecodeError):
            parsed = None
        if not isinstance(parsed, dict):
            parsed = {}

        if 200 <= status < 300 and "error_code" not in parsed:
            return parsed
        return PlaidError(
            error_type=str(parsed.get("error_type") or "UNKNOWN"),
            error_code=str(parsed.get("error_code") or "UNKNOWN"),
            request_id=str(parsed.get("request_id") or ""),
            status=status,
            endpoint=endpoint,
        )
