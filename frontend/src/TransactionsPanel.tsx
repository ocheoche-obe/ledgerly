import { formatCents, type Transaction } from "./api";
import { styles } from "./styles";

// A basic transaction list (FR-2) proving imports landed — date, description, account, and
// signed amount for the default window. Filters, search, and category drill-down come in
// Slice 7; categorization (the Category column would show) is Slice 5, so everything reads
// Uncategorized for now.
export function TransactionsPanel({
  transactions,
  from,
  to,
}: {
  transactions: Transaction[];
  from: string;
  to: string;
}) {
  return (
    <section style={styles.card}>
      <h2 style={styles.sectionTitle}>Transactions</h2>
      <p style={styles.muted}>
        {from} → {to} · {transactions.length}{" "}
        {transactions.length === 1 ? "transaction" : "transactions"}
      </p>

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
                <th style={{ ...styles.th, textAlign: "right" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((t) => (
                <tr key={t.txnId}>
                  <td style={{ ...styles.td, whiteSpace: "nowrap" }}>{t.date}</td>
                  <td style={styles.td}>{t.descriptionRaw}</td>
                  <td style={{ ...styles.td, whiteSpace: "nowrap" }}>{t.accountId}</td>
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
