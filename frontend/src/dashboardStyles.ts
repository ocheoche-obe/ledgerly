// Stylesheet for the dashboard (Slice 6). The rest of the SPA uses inline styles
// (`styles.ts`); the dashboard needs media queries for the phone layout (FR-5.4) and
// :hover/:focus states, which inline styles cannot express — so it gets real CSS, scoped by
// an `ldg-` prefix and injected with the component. No CSS framework: the zero-dependency
// posture of the frontend is deliberate.
//
// Layout intent (NFR-7.1 — readable on desktop without scrolling): four totals tiles, then one
// compact 32px row per category. Fifteen categories plus the totals band fit a laptop viewport.
export const dashboardCss = `
.ldg-dash {
  --ink: #111827;
  --muted: #6b7280;
  --line: #e5e7eb;
  --track: #eef1f5;
  --accent: #2563eb;
  --over: #b91c1c;
  --over-bg: #fef2f2;
  --under: #15803d;
  --warn: #b45309;
  --warn-bg: #fffbeb;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 1.1rem 1.25rem 1.25rem;
  margin-top: 1.5rem;
  color: var(--ink);
}

.ldg-dash-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.ldg-dash-title { margin: 0; font-size: 1.35rem; letter-spacing: -0.01em; }
.ldg-dash-sub { margin: 2px 0 0; color: var(--muted); font-size: 0.85rem; }
.ldg-over-note { color: var(--over); font-weight: 600; }
.ldg-muted { color: var(--muted); font-size: 0.9rem; }

.ldg-picker { display: flex; align-items: center; gap: 8px; }
.ldg-picker-label { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
.ldg-picker select {
  padding: 0.35rem 0.5rem;
  border-radius: 6px;
  border: 1px solid #ccc;
  background: white;
  font-size: 0.9rem;
}

/* --- totals band ------------------------------------------------------------------ */
.ldg-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin: 1rem 0 0.9rem;
}
.ldg-tile {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0.6rem 0.75rem;
  background: #f9fafb;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.ldg-tile-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.ldg-tile-value { font-size: 1.25rem; font-weight: 650; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.ldg-tile-hint { font-size: 0.72rem; color: var(--muted); }
.ldg-tone-in { color: var(--under); }
.ldg-tone-out { color: var(--ink); }
.ldg-tone-over { color: var(--over); }
.ldg-tone-under { color: var(--under); }

.ldg-note {
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.7rem;
  border-radius: 6px;
  background: var(--warn-bg);
  color: var(--warn);
  font-size: 0.85rem;
}
.ldg-note-warn { background: var(--over-bg); color: var(--over); }

/* --- category rows ---------------------------------------------------------------- */
.ldg-rows { list-style: none; margin: 0; padding: 0; }
.ldg-row {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(60px, 1fr) 5.5rem 6.5rem 5.5rem;
  align-items: center;
  gap: 10px;
  padding: 0.3rem 0.35rem;
  border-top: 1px solid #f1f3f5;
  font-size: 0.88rem;
}
.ldg-row:hover { background: #fafbfc; }
.ldg-row-uncat { background: var(--warn-bg); border-radius: 6px; }

.ldg-name { display: flex; align-items: center; gap: 6px; min-width: 0; }
.ldg-name > :first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ldg-count {
  font-size: 0.7rem;
  color: var(--muted);
  background: #f1f3f5;
  border-radius: 10px;
  padding: 0 0.4rem;
}
.ldg-tag {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 0.25rem;
}

.ldg-bar-cell { display: block; }
.ldg-bar { display: block; height: 6px; background: var(--track); border-radius: 3px; overflow: hidden; }
.ldg-bar-fill { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.ldg-bar-over { background: var(--over); }

.ldg-spent, .ldg-left { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ldg-spent { font-weight: 600; }
.ldg-left { color: var(--muted); font-size: 0.82rem; }
.ldg-income { color: var(--under); }
.ldg-over { color: var(--over); }

.ldg-budget { text-align: right; }
.ldg-budget-btn {
  border: 1px solid transparent;
  background: none;
  color: var(--muted);
  font-size: 0.82rem;
  font-family: inherit;
  padding: 0.1rem 0.3rem;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.ldg-budget-btn:hover, .ldg-budget-btn:focus-visible { border-color: var(--line); color: var(--accent); background: white; }
.ldg-budget-input {
  width: 5.5rem;
  padding: 0.1rem 0.3rem;
  border: 1px solid var(--accent);
  border-radius: 5px;
  font: inherit;
  font-size: 0.82rem;
  text-align: right;
}

/* --- phone (FR-5.4) --------------------------------------------------------------- */
@media (max-width: 640px) {
  .ldg-dash { padding: 0.9rem; }
  /* Two lines per category: name + spend on top, bar and budget beneath — nothing is
     dropped, and no horizontal scrolling. */
  .ldg-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "name spent"
      "bar  budget";
    row-gap: 4px;
    padding: 0.45rem 0.35rem;
  }
  .ldg-name { grid-area: name; }
  .ldg-spent { grid-area: spent; }
  .ldg-bar-cell { grid-area: bar; align-self: center; }
  .ldg-budget { grid-area: budget; }
  .ldg-left { display: none; }
  .ldg-tile-value { font-size: 1.1rem; }
}
`;
