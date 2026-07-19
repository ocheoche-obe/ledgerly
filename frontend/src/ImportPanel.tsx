import { useEffect, useState } from "react";
import {
  accountLabelFromFilename,
  type Api,
  type ImportSummary,
} from "./api";
import { styles } from "./styles";

// CSV import (FR-2): pick a bank export, confirm the account it belongs to (pre-filled from
// the filename, ADR-013), then upload. The flow is: POST /imports (presigned URL) → PUT the
// file straight to S3 → poll GET /imports/{id} until the import Lambda reports a result
// (added / duplicate / failed counts, FR-2.5). Recent imports are listed underneath.
const POLL_MS = 1500;
const POLL_TIMEOUT_MS = 90_000;

export function ImportPanel({
  api,
  onImported,
  onError,
}: {
  api: Api;
  onImported: () => void;
  onError: (e: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [accountLabel, setAccountLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<ImportSummary | null>(null); // the in-flight/last import
  const [recent, setRecent] = useState<ImportSummary[]>([]);

  const refreshRecent = () =>
    api.listImports().then(setRecent).catch(() => {}); // list is best-effort

  useEffect(() => {
    refreshRecent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickFile = (f: File | null) => {
    setFile(f);
    if (f && !accountLabel.trim()) setAccountLabel(accountLabelFromFilename(f.name));
  };

  const runImport = async () => {
    if (!file || !accountLabel.trim()) return;
    onError("");
    setBusy(true);
    setActive(null);
    try {
      const created = await api.createImport(file.name, accountLabel.trim());
      await api.uploadFile(created.uploadUrl, file);
      const final = await pollUntilDone(created.importId);
      setActive(final);
      setFile(null);
      await refreshRecent();
      if (final.status === "complete") onImported(); // reveal the new transactions
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const pollUntilDone = async (importId: string): Promise<ImportSummary> => {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    for (;;) {
      const view = await api.getImport(importId);
      setActive(view);
      if (view.done) return view;
      if (Date.now() > deadline) return view; // give up gracefully; status stays visible
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
  };

  return (
    <section style={styles.card}>
      <h2 style={styles.sectionTitle}>Import transactions</h2>

      <div style={styles.row}>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="Bank CSV file"
          onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <div style={styles.row}>
        <label style={{ flex: "1 1 auto", minWidth: 0 }}>
          <span style={styles.label}>Account</span>
          <input
            style={styles.input}
            placeholder="e.g. Chase …5980"
            value={accountLabel}
            aria-label="Account label"
            onChange={(e) => setAccountLabel(e.target.value)}
          />
        </label>
        <button
          style={styles.button}
          onClick={runImport}
          disabled={busy || !file || !accountLabel.trim()}
        >
          {busy ? "Importing…" : "Import"}
        </button>
      </div>

      {active && <ImportResult summary={active} busy={busy} />}

      {recent.length > 0 && (
        <>
          <h3 style={{ ...styles.sectionTitle, marginTop: "1.25rem", fontSize: "1rem" }}>
            Recent imports
          </h3>
          <ul style={styles.list}>
            {recent.map((imp) => (
              <li key={imp.importId} style={styles.listItem}>
                <span style={styles.itemName}>
                  {imp.filename} <span style={styles.muted}>· {imp.accountLabel}</span>
                </span>
                <span style={styles.muted}>{describe(imp)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ImportResult({ summary, busy }: { summary: ImportSummary; busy: boolean }) {
  const label =
    summary.status === "pending" || summary.status === "parsing"
      ? busy
        ? "Working…"
        : summary.status
      : summary.status;
  return (
    <div style={styles.summary} role="status">
      <span>
        <strong>{label}</strong>
      </span>
      {summary.done && (
        <>
          <span>Added: {summary.added}</span>
          <span>Duplicates: {summary.duplicate}</span>
          <span>Failed: {summary.failed}</span>
        </>
      )}
    </div>
  );
}

function describe(imp: ImportSummary): string {
  if (imp.status === "duplicate") return "duplicate file";
  if (imp.status === "failed") return "failed";
  if (!imp.done) return imp.status;
  return `+${imp.added} · ${imp.duplicate} dup · ${imp.failed} failed`;
}
