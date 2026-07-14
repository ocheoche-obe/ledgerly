"""Settings (PROFILE) domain logic.

Pure Python — no AWS imports. This is the portability seam and the unit-test surface
(architecture §0.1, §5.2). Persistence lives in `adapters/`; this module only knows the
*shape* of a settings profile and the rules for a brand-new one.
"""
from __future__ import annotations

from datetime import date

DEFAULT_CADENCE_KIND = "monthly"  # FR-4.2 default cadence


def default_profile(effective_from: str | None = None) -> dict:
    """The PROFILE for a brand-new owner: monthly cadence (FR-4.2 default).

    `effective_from` defaults to the first day of the current month; it is injectable so
    the logic stays deterministic under test.
    """
    eff = effective_from or _first_of_month_today()
    return {
        "type": "PROFILE",
        "cadences": [{"kind": DEFAULT_CADENCE_KIND, "effectiveFrom": eff}],
    }


def settings_view(profile: dict) -> dict:
    """The owner-facing projection of a stored profile (drops internal key attributes)."""
    return {
        "type": profile.get("type", "PROFILE"),
        "cadences": profile.get("cadences", []),
    }


def _first_of_month_today() -> str:
    today = date.today()
    return date(today.year, today.month, 1).isoformat()
