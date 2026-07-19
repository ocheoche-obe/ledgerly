"""Exhaustive unit tests for the budget-cycle engine (core/cycles.py, FR-4.2).

Covers both cadences (monthly + biweekly), month/anchor boundary math, and — the part that
matters most — cadence *transitions*: that a change takes effect only from the next cycle
and never rewrites a past cycle.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.cycles import (
    Cycle,
    cycle_for,
    cycle_id_for,
    next_cycle_start,
    plan_cadence_change,
)

MONTHLY = [{"kind": "monthly", "effectiveFrom": "2026-01-01"}]
BIWEEKLY = [{"kind": "biweekly", "anchor": "2026-07-10", "effectiveFrom": "2026-07-10"}]


# --- Monthly cadence -------------------------------------------------------------------

def test_monthly_id_and_window_midmonth():
    c = cycle_for(MONTHLY, date(2026, 7, 15))
    assert c == Cycle("M#2026-07", "monthly", date(2026, 7, 1), date(2026, 7, 31))


@pytest.mark.parametrize(
    "on, cid, start, end",
    [
        (date(2026, 2, 1), "M#2026-02", date(2026, 2, 1), date(2026, 2, 28)),  # 28-day month
        (date(2028, 2, 29), "M#2028-02", date(2028, 2, 1), date(2028, 2, 29)),  # leap year
        (date(2026, 1, 1), "M#2026-01", date(2026, 1, 1), date(2026, 1, 31)),  # first-of-month
        (date(2026, 12, 31), "M#2026-12", date(2026, 12, 1), date(2026, 12, 31)),  # year end
    ],
)
def test_monthly_boundaries(on, cid, start, end):
    assert cycle_for(MONTHLY, on) == Cycle(cid, "monthly", start, end)


def test_monthly_next_cycle_start_rolls_the_year():
    assert next_cycle_start(MONTHLY, date(2026, 12, 20)) == date(2027, 1, 1)


# --- Biweekly cadence ------------------------------------------------------------------

def test_biweekly_window_on_anchor():
    c = cycle_for(BIWEEKLY, date(2026, 7, 10))
    assert c == Cycle("B#2026-07-10", "biweekly", date(2026, 7, 10), date(2026, 7, 23))


def test_biweekly_last_day_of_window_is_inclusive():
    assert cycle_for(BIWEEKLY, date(2026, 7, 23)).cycle_id == "B#2026-07-10"
    # The next day rolls into the following 14-day cycle.
    assert cycle_for(BIWEEKLY, date(2026, 7, 24)).cycle_id == "B#2026-07-24"


def test_biweekly_second_and_third_cycles():
    assert cycle_id_for(BIWEEKLY, date(2026, 8, 6)) == "B#2026-07-24"
    assert cycle_id_for(BIWEEKLY, date(2026, 8, 7)) == "B#2026-08-07"


def test_biweekly_phase_locks_before_the_anchor():
    # Floor division keeps the rhythm consistent for dates earlier than the anchor.
    c = cycle_for(BIWEEKLY, date(2026, 7, 9))
    assert c == Cycle("B#2026-06-26", "biweekly", date(2026, 6, 26), date(2026, 7, 9))


def test_biweekly_next_cycle_start():
    assert next_cycle_start(BIWEEKLY, date(2026, 7, 15)) == date(2026, 7, 24)


# --- Cadence transitions (the FR-4.2 crux) --------------------------------------------

def test_monthly_to_biweekly_past_cycles_unchanged():
    # Owner on monthly since Jan switches to biweekly anchored to a future payday.
    cadences = plan_cadence_change(
        MONTHLY, kind="biweekly", anchor=date(2026, 9, 4), today=date(2026, 8, 15)
    )
    # A past date still resolves to the monthly cycle it always did.
    assert cycle_for(cadences, date(2026, 3, 10)) == Cycle(
        "M#2026-03", "monthly", date(2026, 3, 1), date(2026, 3, 31)
    )
    # The current cycle (August) is untouched — the change is in the future.
    assert cycle_id_for(cadences, date(2026, 8, 15)) == "M#2026-08"


def test_monthly_to_biweekly_takes_effect_on_future_payday():
    cadences = plan_cadence_change(
        MONTHLY, kind="biweekly", anchor=date(2026, 9, 4), today=date(2026, 8, 15)
    )
    # Anchor (Sep 4) is past the next boundary (Sep 1) → biweekly starts exactly on payday,
    # no truncation, and the outgoing monthly cadence runs right up to it.
    assert cycle_for(cadences, date(2026, 8, 31)) == Cycle(
        "M#2026-08", "monthly", date(2026, 8, 1), date(2026, 8, 31)
    )
    assert cycle_for(cadences, date(2026, 9, 3)) == Cycle(
        "M#2026-09", "monthly", date(2026, 9, 1), date(2026, 9, 3)
    )  # truncated tail of the outgoing cadence — same natural ID, shorter window
    assert cycle_for(cadences, date(2026, 9, 4)) == Cycle(
        "B#2026-09-04", "biweekly", date(2026, 9, 4), date(2026, 9, 17)
    )


def test_biweekly_change_deferred_when_payday_is_within_current_cycle():
    # Payday is before the next monthly boundary → change can't rewrite the current cycle,
    # so it defers to the boundary but stays phase-locked to the payday rhythm.
    cadences = plan_cadence_change(
        MONTHLY, kind="biweekly", anchor=date(2026, 8, 20), today=date(2026, 8, 10)
    )
    entry = cadences[-1]
    assert entry["effectiveFrom"] == "2026-09-01"  # deferred to next boundary
    assert entry["anchor"] == "2026-08-20"  # phase preserved
    # First active biweekly cycle is the natural window containing Sep 1, clamped to start
    # at the effectiveFrom boundary.
    c = cycle_for(cadences, date(2026, 9, 1))
    assert c.cycle_id == "B#2026-08-20"
    assert c.start == date(2026, 9, 1)
    assert c.end == date(2026, 9, 2)  # natural window 2026-08-20..09-02, clamped at the front


def test_biweekly_to_monthly_takes_effect_next_boundary():
    cadences = plan_cadence_change(BIWEEKLY, kind="monthly", today=date(2026, 7, 15))
    entry = cadences[-1]
    # Current biweekly cycle is 07-10..07-23 → monthly resumes 07-24.
    assert entry == {"kind": "monthly", "effectiveFrom": "2026-07-24"}
    # The tail biweekly cycle is untouched; the new monthly cycle is clamped at the front.
    assert cycle_id_for(cadences, date(2026, 7, 20)) == "B#2026-07-10"
    c = cycle_for(cadences, date(2026, 7, 28))
    assert c == Cycle("M#2026-07", "monthly", date(2026, 7, 24), date(2026, 7, 31))


def test_plan_change_rejects_non_advancing_timeline():
    # Applying a change "today" that resolves to an effectiveFrom already present must fail.
    cadences = plan_cadence_change(MONTHLY, kind="monthly", today=date(2026, 8, 15))
    with pytest.raises(ValueError, match="take effect after"):
        # Re-applying against the same 'today' yields the same boundary → not advancing.
        plan_cadence_change(cadences, kind="monthly", today=date(2026, 7, 1))


def test_plan_biweekly_requires_anchor():
    with pytest.raises(ValueError, match="requires an anchor"):
        plan_cadence_change(MONTHLY, kind="biweekly", today=date(2026, 8, 15))


def test_plan_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown cadence kind"):
        plan_cadence_change(MONTHLY, kind="weekly", today=date(2026, 8, 15))


def test_three_cadence_history_resolves_each_era():
    # monthly → biweekly → back to monthly, each era resolving to its own cadence.
    c1 = plan_cadence_change(
        MONTHLY, kind="biweekly", anchor=date(2026, 4, 3), today=date(2026, 3, 10)
    )
    c2 = plan_cadence_change(c1, kind="monthly", today=date(2026, 6, 10))
    assert cycle_id_for(c2, date(2026, 2, 15)) == "M#2026-02"  # era 1
    assert cycle_id_for(c2, date(2026, 4, 17)) == "B#2026-04-17"  # era 2
    assert cycle_id_for(c2, date(2026, 8, 15)) == "M#2026-08"  # era 3


def test_empty_cadences_raises():
    with pytest.raises(ValueError, match="no cadences"):
        cycle_for([], date(2026, 7, 1))
