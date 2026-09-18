import { useEffect, useMemo, useState } from "react";
import {
  formatCents,
  UNCATEGORIZED_ROW_ID,
  type Api,
  type CategorySummary,
  type Cycle,
  type CycleSummary,
} from "./api";
import { dashboardCss } from "./dashboardStyles";

// The product's core screen (FR-5.1): budget vs. actual per category for one cycle, plus
// totals, answerable at a glance. NFR-7.1 makes "at a glance" testable — the current cycle's
// position has to be readable on desktop without scrolling — so rows are deliberately compact
// and the four numbers that matter sit above them.
//
// This is the one panel with a real visual pass (owner decision, 2026-08-07); the rest of the
// SPA keeps its plain inline styles until [B-3]'s app-wide pass. It uses a stylesheet rather
// than inline styles because the layout needs media queries (FR-5.4, phone) and :hover/:focus,
// none of which inline styles can express.

function cycleLabel(cycle: Cycle): string {
  const start = new Date(`${cycle.start}T00:00:00`);
  const end = new Date(`${cycle.end}T00:00:00`);
  const month = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  if (cycle.kind === "monthly") {
    return start.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  }
  return `${month(start)} – ${month(end)}`;
}

// Dollars typed by the owner → integer cents. Returns null for an empty field (= clear the
// budget) and undefined for anything unparseable, so the caller can leave the value alone.
function parseDollars(input: string): number | null | undefined {
  const trimmed = input.trim().replace(/^\$/, "").replace(/,/g, "");
  if (!trimmed) return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0) return undefined;
  return Math.round(value * 100);
}

export function DashboardPanel({
  api,
  onError,
  reloadKey,
}: {
  api: Api;
  onError: (message: string) => void;
  // Bumped by the parent after an import or recategorize so the dashboard re-reads.
  reloadKey: number;
}) {
  const [cycles, setCycles] = useState<Cycle[] | null>(null);
  const [selected, setSelected] = useState<string>("current");
  const [summary, setSummary] = useState<CycleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    api
      .listCycles()
      .then((r) => setCycles(r.cycles))
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
    // The picker's contents only change when data does, so it rides the same reload signal.
  }, [api, reloadKey]);

  useEffect(() => {
    setLoading(true);
    api
      .getCycleSummary(selected)
      .then(setSummary)
      .catch((e) => onError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [api, selected, reloadKey]);

  const saveBudget = async (row: CategorySummary) => {
    const amount = parseDollars(draft);
    setEditing(null);
    if (amount === undefined) return; // unparseable — discard the edit, keep the old value
    if (amount === row.budgetCents) return;
    try {
      await api.setBudget(selected, row.categoryId, amount);
      setSummary(await api.getCycleSummary(selected));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const totals = summary?.totals;
  const rows = summary?.perCategory ?? [];
  const overCount = useMemo(() => rows.filter((r) => r.over).length, [rows]);

  return (
    <section className="ldg-dash">
      <style>{dashboardCss}</style>

      <header className="ldg-dash-head">
        <div>
          <h2 className="ldg-dash-title">
            {summary ? cycleLabel(summary.cycle) : "Dashboard"}
          </h2>
          {summary && (
            <p className="ldg-dash-sub">
              {summary.cycle.start} → {summary.cycle.end} ·{" "}
              {totals?.transactionCount ?? 0} transactions
              {overCount > 0 && (
                <>
                  {" · "}
                  <span className="ldg-over-note">
                    {overCount} over budget
                  </span>
                </>
              )}
            </p>
          )}
        </div>
        <label className="ldg-picker">
          <span className="ldg-picker-label">Cycle</span>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={!cycles}
          >
            <option value="current">Current</option>
            {(cycles ?? []).map((c) => (
              // Addressed by a date inside the cycle — the '#' in a cycle ID would have to
              // survive URL encoding, and a mis-encoded ID would silently address nothing.
              <option key={c.cycleId} value={c.start}>
                {cycleLabel(c)}
              </option>
            ))}
          </select>
        </label>
      </header>

      {loading && !summary ? (
        <p className="ldg-muted">Loading dashboard…</p>
      ) : !totals ? null : (
        <>
          <div className="ldg-tiles">
            <Tile label="Money in" value={formatCents(totals.moneyInCents)} tone="in" />
            {/* Both magnitudes are shown unsigned — the labels already say the direction, and a
                minus on "money out" reads as a double negative. The net says which way it went. */}
            <Tile
              label="Money out"
              value={formatCents(totals.moneyOutCents)}
              hint={
                totals.netCents < 0
                  ? `${formatCents(-totals.netCents)} more than came in`
                  : `${formatCents(totals.netCents)} left over`
              }
            />
            <Tile label="Budgeted" value={formatCents(totals.budgetedCents)} />
            <Tile
              label="Remaining"
              value={formatCents(totals.remainingCents)}
              tone={totals.remainingCents < 0 ? "over" : "under"}
              hint={
                totals.budgetedCents === 0
                  ? "no budgets set yet"
                  : `of ${formatCents(totals.budgetedCents)} budgeted`
              }
            />
          </div>

          {totals.uncategorizedCount > 0 && (
            <p className="ldg-note">
              {totals.uncategorizedCount} transaction
              {totals.uncategorizedCount === 1 ? " is" : "s are"} still uncategorized — that
              money is in the totals but not in any category. Use{" "}
              <strong>Recategorize this window</strong> below.
            </p>
          )}
          {totals.truncated && (
            <p className="ldg-note ldg-note-warn">
              This cycle has more transactions than one query returns, so the figures below
              under-report it.
            </p>
          )}

          <ul className="ldg-rows">
            {rows.map((row) => {
              const isIncome = row.spentCents < 0;
              const isUncategorized = row.categoryId === UNCATEGORIZED_ROW_ID;
              const pct =
                row.budgetCents && row.budgetCents > 0
                  ? Math.min(100, Math.max(0, (row.spentCents / row.budgetCents) * 100))
                  : 0;
              return (
                <li
                  key={row.categoryId}
                  className={`ldg-row${isUncategorized ? " ldg-row-uncat" : ""}`}
                >
                  <span className="ldg-name">
                    {row.name}
                    {row.archived && <span className="ldg-tag">archived</span>}
                    {row.transactionCount > 0 && (
                      <span className="ldg-count">{row.transactionCount}</span>
                    )}
                  </span>

                  <span className="ldg-bar-cell">
                    {row.budgetCents !== null && row.budgetCents > 0 && (
                      <span className="ldg-bar" aria-hidden="true">
                        <span
                          className={`ldg-bar-fill${row.over ? " ldg-bar-over" : ""}`}
                          style={{ width: `${row.over ? 100 : pct}%` }}
                        />
                      </span>
                    )}
                  </span>

                  <span
                    className={`ldg-spent${isIncome ? " ldg-income" : ""}${
                      row.over ? " ldg-over" : ""
                    }`}
                  >
                    {isIncome ? formatCents(-row.spentCents) : formatCents(row.spentCents)}
                  </span>

                  <span className="ldg-budget">
                    {editing === row.categoryId ? (
                      <input
                        className="ldg-budget-input"
                        autoFocus
                        inputMode="decimal"
                        value={draft}
                        placeholder="0.00"
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={() => saveBudget(row)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") e.currentTarget.blur();
                          if (e.key === "Escape") setEditing(null);
                        }}
                      />
                    ) : isUncategorized ? (
                      <span className="ldg-muted">—</span>
                    ) : (
                      <button
                        className="ldg-budget-btn"
                        onClick={() => {
                          setEditing(row.categoryId);
                          setDraft(
                            row.budgetCents === null
                              ? ""
                              : (row.budgetCents / 100).toFixed(2),
                          );
                        }}
                        title="Set this category's budget for this cycle"
                      >
                        {row.budgetCents === null
                          ? "set budget"
                          : `of ${formatCents(row.budgetCents)}`}
                      </button>
                    )}
                  </span>

                  <span
                    className={`ldg-left${row.over ? " ldg-over" : ""}`}
                    title={row.budgetCents === null ? "" : "remaining"}
                  >
                    {row.remainingCents === null ? "" : formatCents(row.remainingCents)}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function Tile({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: "in" | "out" | "over" | "under";
  hint?: string;
}) {
  return (
    <div className="ldg-tile">
      <span className="ldg-tile-label">{label}</span>
      <span className={`ldg-tile-value${tone ? ` ldg-tone-${tone}` : ""}`}>{value}</span>
      {hint && <span className="ldg-tile-hint">{hint}</span>}
    </div>
  );
}
