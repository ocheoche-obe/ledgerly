"""Unit tests for the pure settings domain (no AWS)."""
from datetime import date

from core.settings import default_profile, settings_view


def test_default_profile_is_monthly_with_given_effective_date():
    profile = default_profile(effective_from="2026-07-01")
    assert profile["type"] == "PROFILE"
    assert profile["cadences"] == [{"kind": "monthly", "effectiveFrom": "2026-07-01"}]


def test_default_profile_defaults_to_first_of_current_month():
    profile = default_profile()
    today = date.today()
    expected = date(today.year, today.month, 1).isoformat()
    assert profile["cadences"][0] == {"kind": "monthly", "effectiveFrom": expected}


def test_settings_view_drops_key_attributes():
    stored = {
        "pk": "USER#abc",
        "sk": "PROFILE",
        "type": "PROFILE",
        "cadences": [{"kind": "monthly", "effectiveFrom": "2026-07-01"}],
    }
    view = settings_view(stored)
    assert view == {
        "type": "PROFILE",
        "cadences": [{"kind": "monthly", "effectiveFrom": "2026-07-01"}],
    }
    assert "pk" not in view and "sk" not in view


def test_settings_view_tolerates_missing_fields():
    assert settings_view({}) == {"type": "PROFILE", "cadences": []}
