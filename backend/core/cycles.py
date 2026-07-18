"""Budget-cycle engine (FR-4.2) — the cycle math everything downstream keys on.

Pure Python, no AWS imports (the portability seam + unit-test surface, architecture §5.2).
This module owns three things and nothing else:

1. **Cycle identity & windows.** A date maps to exactly one cycle, identified by cadence +
   start date: ``M#2026-07`` (calendar month) or ``B#2026-07-10`` (two-week, anchored).
   Cycle IDs are *derived* from the settings ``cadences`` history — never stored on
   transactions (architecture §2.4). A transaction stores its date; its cycle is computed.

2. **Cadence history semantics.** ``cadences`` is an append-only list, each entry owning
   ``[effectiveFrom, next.effectiveFrom)``. Because a change only ever *appends* a future
   entry, past dates always resolve to the cadence that was in force then — a cadence change
   never rewrites a past cycle (FR-4.2).

3. **Applying a cadence change.** ``plan_cadence_change`` computes the ``effectiveFrom`` so
   the change lands on a future boundary and leaves the *current* cycle untouched
   ("takes effect from the next cycle", FR-4.2).

Windows are **clamped** to the owning cadence's span, so no single cycle ever straddles a
cadence change: the transition cycle is simply shorter. Clamping preserves the *natural*
cycle ID (e.g. a truncated ``M#2026-09``), so IDs stay stable and meaningful downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

BIWEEKLY_DAYS = 14


@dataclass(frozen=True)
class Cycle:
    """A resolved budget cycle: stable ID + inclusive [start, end] window."""

    cycle_id: str
    kind: str  # "monthly" | "biweekly"
    start: date
    end: date  # inclusive

    def as_view(self) -> dict:
        """Owner-facing projection (ISO dates), safe to serialize to the API."""
        return {
            "cycleId": self.cycle_id,
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def _parse(iso: str) -> date:
    return date.fromisoformat(iso)


def _last_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _natural_window(cadence: dict, on: date) -> tuple[str, str, date, date]:
    """The unclamped cycle (id, kind, start, end) a date falls in under one cadence."""
    kind = cadence["kind"]
    if kind == "monthly":
        start = date(on.year, on.month, 1)
        end = _last_of_month(on)
        return f"M#{start:%Y-%m}", kind, start, end
    if kind == "biweekly":
        anchor = _parse(cadence["anchor"])
        # Floor division (toward -inf) phase-locks windows to the anchor even for dates
        # before it, so the payday rhythm is consistent in both directions.
        k = (on - anchor).days // BIWEEKLY_DAYS
        start = anchor + timedelta(days=BIWEEKLY_DAYS * k)
        end = start + timedelta(days=BIWEEKLY_DAYS - 1)
        return f"B#{start:%Y-%m-%d}", kind, start, end
    raise ValueError(f"unknown cadence kind: {kind!r}")


def _sorted_cadences(cadences: list[dict]) -> list[dict]:
    if not cadences:
        raise ValueError("settings has no cadences")
    return sorted(cadences, key=lambda c: c["effectiveFrom"])


def _active_index(cadences: list[dict], on: date) -> int:
    """Index of the cadence in force on `on`: the last one whose effectiveFrom <= on."""
    ordered = _sorted_cadences(cadences)
    idx = 0
    for i, c in enumerate(ordered):
        if _parse(c["effectiveFrom"]) <= on:
            idx = i
        else:
            break
    return idx


def cycle_for(cadences: list[dict], on: date) -> Cycle:
    """The single cycle a date belongs to, clamped to its cadence's span.

    Clamping guarantees no cycle straddles a cadence change: the window is trimmed to
    ``[effectiveFrom, next.effectiveFrom - 1]`` while keeping the natural cycle ID.
    """
    ordered = _sorted_cadences(cadences)
    idx = _active_index(ordered, on)
    active = ordered[idx]

    cycle_id, kind, start, end = _natural_window(active, on)

    # The earliest cadence (idx 0) extends backward indefinitely, so back-dated imports
    # (transactions predating account creation) still map to a cycle. Only a *later* cadence
    # clamps its front, where a real predecessor owns the earlier dates.
    if idx > 0:
        lo = _parse(active["effectiveFrom"])
        if start < lo:
            start = lo
    if idx + 1 < len(ordered):
        hi = _parse(ordered[idx + 1]["effectiveFrom"]) - timedelta(days=1)
        if end > hi:
            end = hi
    return Cycle(cycle_id=cycle_id, kind=kind, start=start, end=end)


def cycle_id_for(cadences: list[dict], on: date) -> str:
    """Just the cycle ID for a date — the key component transactions/budgets derive."""
    return cycle_for(cadences, on).cycle_id


def next_cycle_start(cadences: list[dict], on: date) -> date:
    """First day of the cycle immediately after the one containing `on`."""
    return cycle_for(cadences, on).end + timedelta(days=1)


def plan_cadence_change(
    cadences: list[dict],
    *,
    kind: str,
    today: date,
    anchor: date | None = None,
) -> list[dict]:
    """Append a future cadence entry, effective from the next cycle (FR-4.2).

    - ``effectiveFrom`` never falls inside the current cycle, so the current and all past
      cycles are untouched ("never rewrites past cycles").
    - Monthly targets take effect at the next cycle boundary.
    - Biweekly targets require an ``anchor`` (the owner's payday). If the payday is already
      past the next boundary the change lands exactly on it (no truncation); otherwise it
      defers to the next boundary, still phase-locked to the payday.

    Returns a new cadences list (input is not mutated). Raises ValueError on a change that
    would not advance the timeline (e.g. a duplicate effectiveFrom).
    """
    if kind not in ("monthly", "biweekly"):
        raise ValueError(f"unknown cadence kind: {kind!r}")

    boundary = next_cycle_start(cadences, today)

    if kind == "biweekly":
        if anchor is None:
            raise ValueError("biweekly cadence requires an anchor date")
        effective_from = anchor if anchor >= boundary else boundary
        entry = {
            "kind": "biweekly",
            "anchor": anchor.isoformat(),
            "effectiveFrom": effective_from.isoformat(),
        }
    else:
        entry = {"kind": "monthly", "effectiveFrom": boundary.isoformat()}

    ordered = _sorted_cadences(cadences)
    last_effective = _parse(ordered[-1]["effectiveFrom"])
    if _parse(entry["effectiveFrom"]) <= last_effective:
        raise ValueError(
            "cadence change must take effect after the current cadence "
            f"({entry['effectiveFrom']} <= {ordered[-1]['effectiveFrom']})"
        )

    return [*ordered, entry]
