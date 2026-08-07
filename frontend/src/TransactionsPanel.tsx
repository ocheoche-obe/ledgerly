import { useState } from "react";
import {
  formatCents,
  type Api,
  type Category,
  type RecategorizeResult,
  type Transaction,
} from "./api";
import { styles } from "./styles";

// A basic transaction list (FR-2) proving imports landed — date, description, account, signed
// amount, and the auto-assigned Category (Slice 5). The Category cell reflects the async
// pipeline: a row reads "Uncategorized" until the categorizer runs (~seconds after import),
// then shows the category name — with a "review" tag when the model's confidence was low.
// Filters, search, and category drill-down come in Slice 7.
//
// Slice 6 adds the **Recategorize** control ([B-7]): the only way to categorize transactions
// that were imported before the categorizer existed, since re-importing them adds 0 rows
// (ADR-012) and therefore enqueues nothing. It is deliberately in the UI rather than a script —
// the owner has no other way to mint an authorized request.
export function TransactionsPanel({
  api,
  transactions,
  categories,
  from,
  to,
  onRecategorized,
  onError,
}: {
  api: Api;
  transactions: Transaction[];
  categories: Category[];
  from: string;
  to: string;
  onRecategorized: () => void;
  onError: (message: string) => void;
}) {
  const nameById = new Map(categories.map((c) => [c.categoryId, c.name]));
  const [includeCategorized, setIncludeCategorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RecategorizeResult | null>(null);

  const uncategorized = transactions.filter((t) => !t.categoryId).length;

  const recategorize = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await api.recategorize(from, to, includeCategorized);
      setResult(res);
      // The categorizer works off SQS, so nothing has changed yet. Refresh after a beat so the
      // rows visibly fill in; the owner can also just reload if a big batch takes longer.
      setTimeout(onRecategorized, 8000);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={styles.card}>
      <h2 style={styles.sectionTitle}>Transactions</h2>
      <p style={styles.muted}>
        {from} → {to} · {transactions.length}{" "}
        {transactions.length === 1 ? "transaction" : "transactions"}
        {uncategorized > 0 && ` · ${uncategorized} uncategorized`}
      </p>

      <div style={styles.row}>
        <button style={styles.buttonGhost} onClick={recategorize} disabled={busy}>
          {busy ? "Queueing…" : "Recategorize this window"}
        </button>
        <label style={{ ...styles.muted, display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={includeCategorized}
            onChange={(e) => setIncludeCategorized(e.target.checked)}
          />
          also re-run already-categorized
        </label>
      </div>
      {result && (
        <p style={styles.muted}>
          Queued {result.enqueued} of {result.scanned} transaction
          {result.scanned === 1 ? "" : "s"} in {result.messages} batch
          {result.messages === 1 ? "" : "es"} — categorizing runs in the background, so the
          list fills in shortly.
          {result.truncated && ` ⚠ ${result.message}`}
        </p>
      )}

      {transactions.length === 0 ? (
        <p style={styles.muted}>No transactions in this window yet — import a CSV above.</p>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Description</th>
                <th style={styles.th}>Account</th>
                <th style={styles.th}>Category</th>
                <th style={{ ...styles.th, textAlign: "right" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((t) => (
                <tr key={t.txnId}>
                  <td style={{ ...styles.td, whiteSpace: "nowrap" }}>{t.date}</td>
                  <td style={styles.td}>{t.descriptionRaw}</td>
                  <td style={{ ...styles.td, whiteSpace: "nowrap" }}>{t.accountId}</td>
                  <td style={styles.td}>
                    {t.categoryId ? (
                      <>
                        {nameById.get(t.categoryId) ?? t.categoryId}
                        {t.needsReview && <span style={styles.muted}> · review</span>}
                      </>
                    ) : (
                      <span style={styles.muted}>Uncategorized</span>
                    )}
                  </td>
                  <td
                    style={{
                      ...styles.td,
                      ...(t.direction === "credit" ? styles.amountCredit : styles.amountDebit),
                    }}
                  >
                    {formatCents(t.amountCents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
