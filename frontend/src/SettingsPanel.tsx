import { useState } from "react";
import type { Api, CadenceKind, Settings } from "./api";
import { styles } from "./styles";

// Budget-cycle settings (FR-4.2): shows the cadence in force + the current cycle window,
// and lets the owner switch between monthly and two-week (payday-anchored). A change takes
// effect from the next cycle — the backend enforces that; here we just surface it.
export function SettingsPanel({
  api,
  settings,
  onChange,
  onError,
}: {
  api: Api;
  settings: Settings;
  onChange: (s: Settings) => void;
  onError: (e: string) => void;
}) {
  // The cadence in force is the latest one whose effectiveFrom is not in the future — the
  // same rule the backend engine uses. The last array element may be a *scheduled* future
  // cadence, so picking it would contradict the current-cycle line below.
  const today = new Date().toISOString().slice(0, 10);
  const inForce = [...settings.cadences]
    .sort((a, b) => a.effectiveFrom.localeCompare(b.effectiveFrom))
    .filter((c) => c.effectiveFrom <= today);
  const active = inForce[inForce.length - 1] ?? settings.cadences[0];
  const [kind, setKind] = useState<CadenceKind>(active.kind);
  const [anchor, setAnchor] = useState<string>(active.anchor ?? "");
  const [saving, setSaving] = useState(false);

  const cycle = settings.currentCycle;

  const save = async () => {
    onError("");
    if (kind === "biweekly" && !anchor) {
      onError("Pick a start date (your payday) for the two-week cycle.");
      return;
    }
    setSaving(true);
    try {
      const updated = await api.setCadence(kind, kind === "biweekly" ? anchor : undefined);
      onChange(updated);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section style={styles.card}>
      <h2 style={styles.sectionTitle}>Budget cycle</h2>
      <p style={styles.muted}>
        Current cycle <strong>{cycle.cycleId}</strong> — {cycle.start} to {cycle.end} (
        {cycle.kind})
      </p>

      <div style={styles.row}>
        <label htmlFor="cadence-kind" style={styles.muted}>
          Cadence
        </label>
        <select
          id="cadence-kind"
          style={styles.select}
          value={kind}
          onChange={(e) => setKind(e.target.value as CadenceKind)}
        >
          <option value="monthly">Monthly (calendar month)</option>
          <option value="biweekly">Two-week (payday-aligned)</option>
        </select>

        {kind === "biweekly" && (
          <input
            type="date"
            aria-label="Cycle start date (payday)"
            style={styles.select}
            value={anchor}
            onChange={(e) => setAnchor(e.target.value)}
          />
        )}

        <button style={styles.button} onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save cadence"}
        </button>
      </div>
      <p style={styles.muted}>Changes take effect from the next cycle; past cycles are never rewritten.</p>
    </section>
  );
}
