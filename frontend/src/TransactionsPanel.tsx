import { formatCents, type Category, type Transaction } from "./api";
import { styles } from "./styles";

// A basic transaction list (FR-2) proving imports landed — date, description, account, signed
// amount, and the auto-assigned Category (Slice 5). The Category cell reflects the async
// pipeline: a row reads "Uncategorized" until the categorizer runs (~seconds after import),
// then shows the category name — with a "review" tag when the model's confidence was low.
// Filters, search, and category drill-down come in Slice 7.
export function TransactionsPanel({
  transactions,
  categories,
  from,
  to,
}: {
  transactions: Transaction[];
  categories: Category[];
  from: string;
  to: string;
}) {
  const nameById = new Map(categories.map((c) => [c.categoryId, c.name]));
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
