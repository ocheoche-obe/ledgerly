// Typed client for the Ledgerly HTTP API. Every call carries the Cognito access token in
// the Authorization header (the API Gateway JWT authorizer verifies it); identity is derived
// server-side from the token, never sent in the body (FR-1.3).

export type CadenceKind = "monthly" | "biweekly";

export interface Cadence {
  kind: CadenceKind;
  anchor?: string; // ISO date, biweekly only
  effectiveFrom: string; // ISO date
}

export interface Cycle {
  cycleId: string; // "M#2026-07" | "B#2026-07-10"
  kind: CadenceKind;
  start: string; // ISO date, inclusive
  end: string; // ISO date, inclusive
}

export interface Settings {
  type: string;
  cadences: Cadence[];
  currentCycle: Cycle;
}

export type CategoryStatus = "active" | "archived";

export interface Category {
  categoryId: string;
  name: string;
  status: CategoryStatus;
  sortOrder: number;
}

export type ImportStatus =
  | "pending"
  | "parsing"
  | "complete"
  | "duplicate"
  | "failed";

export interface ImportSummary {
  importId: string;
  filename: string;
  accountLabel: string;
  /** "csv" for a file upload, "plaid" for a bank sync (ADR-014). */
  source?: "csv" | "plaid";
  status: ImportStatus;
  added: number;
  /** Plaid syncs only: rows Plaid changed (incl. pending charges that posted) / deleted. */
  modified?: number;
  removed?: number;
  duplicate: number;
  failed: number;
  errors: { line?: number; error: string }[];
  createdAt: string;
  done: boolean;
}

// POST /imports response = the pending summary plus the presigned upload URL.
export interface CreatedImport extends ImportSummary {
  uploadUrl: string;
}

export type TxnDirection = "debit" | "credit";

export interface Transaction {
  txnId: string;
  date: string; // YYYY-MM-DD
  amountCents: number; // signed: negative = debit
  direction: TxnDirection;
  /** Null on Plaid rows: Plaid supplies no running balance (ADR-014). */
  balanceCents: number | null;
  accountId: string;
  descriptionRaw: string;
  merchantNormalized: string;
  categoryId: string | null;
  categoryStatus: string;
  confidence: number | null;
  needsReview: boolean;
  importId: string;
  /** A Plaid charge that hasn't posted yet: its amount can still change, or it can vanish. */
  pending?: boolean;
  source?: "csv" | "plaid";
}

// --- budgets & dashboard (Slice 6, FR-4.3 / FR-5) --------------------------------------

// One dashboard row. `budgetCents` is null when no target was set — distinct from a $0 target.
// `spentCents` is money *out* (a negated net, so refunds reduce it); an income category reports
// negative spend. `categoryId` is the synthetic "__uncategorized__" on the uncategorized row.
export interface CategorySummary {
  categoryId: string;
  name: string;
  budgetCents: number | null;
  spentCents: number;
  /** The part of spentCents that is still pending at the bank (already included in it). */
  pendingSpentCents?: number;
  netCents: number;
  transactionCount: number;
  remainingCents: number | null;
  over: boolean;
  archived: boolean;
}

export interface CycleTotals {
  moneyInCents: number;
  moneyOutCents: number;
  netCents: number;
  budgetedCents: number;
  spentAgainstBudgetCents: number;
  remainingCents: number;
  transactionCount: number;
  uncategorizedCount: number;
  /** Already included in the figures above — the part of them that is not final yet. */
  pendingSpentCents?: number;
  pendingCount?: number;
  truncated?: boolean;
}

export interface CycleSummary {
  cycle: Cycle;
  perCategory: CategorySummary[];
  totals: CycleTotals;
}

export const UNCATEGORIZED_ROW_ID = "__uncategorized__";

// A cycle is addressed in the API by `current` or any ISO date inside it — never by the raw
// cycle ID, whose '#' would have to survive URL encoding. The server derives the canonical ID.
export type CycleRef = "current" | string;

// POST /transactions/recategorize — the async re-drive ([B-7]). Returns what was *enqueued*,
// not what was categorized: the categorizer runs behind SQS, so the list refreshes seconds later.
export interface RecategorizeResult {
  from: string;
  to: string;
  includeCategorized: boolean;
  scanned: number;
  enqueued: number;
  messages: number;
  truncated?: boolean;
  message?: string;
}

// --- bank connections (Plaid Sandbox, Slice 9 / ADR-014) -------------------------------

// One account at a connected bank. Balances are Plaid's *cached* figures as of the last sync,
// not a real-time balance; null when the bank doesn't report one.
export interface BankAccount {
  plaidAccountId: string;
  accountId: string; // the label its transactions carry, e.g. "plaid-checking-0000"
  name: string;
  officialName: string;
  mask: string;
  type: string;
  subtype: string;
  balanceCurrentCents: number | null;
  balanceAvailableCents: number | null;
  currency: string;
}

// A connected institution (a Plaid "Item"). The browser never sees an access token — only this.
export interface BankConnection {
  itemId: string;
  institutionId: string;
  institutionName: string;
  accounts: BankAccount[];
  plaidEnv: string;
  createdAt: string;
  lastSyncedAt: string; // "" until the first sync completes
  errorCode: string; // Plaid error from the last failed sync; "" when healthy
  errorAt: string;
  needsReconnect: boolean; // the fix is logging in again (Link update mode)
}

export interface LinkToken {
  linkToken: string;
  expiration: string;
  mode: "link" | "update";
}

// What Link's onSuccess hands us, forwarded so the server can label, dedupe and support-debug
// the connection. The public token is single-use and is exchanged server-side immediately.
export interface ExchangeRequest {
  publicToken: string;
  institution: { id: string; name: string } | null;
  linkSessionId: string;
}

export interface ExchangedConnection extends BankConnection {
  importId: string; // the first sync, started automatically
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const POLL_MS = 1500;
const POLL_TIMEOUT_MS = 90_000;

// Poll GET /imports/{id} until it reports a terminal status (or the deadline passes, in which
// case the last view is returned as-is). Serves both CSV imports and Plaid syncs.
export async function pollImport(
  api: Api,
  importId: string,
  onUpdate?: (view: ImportSummary) => void,
  { intervalMs = POLL_MS, timeoutMs = POLL_TIMEOUT_MS } = {},
): Promise<ImportSummary> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const view = await api.getImport(importId);
    onUpdate?.(view);
    if (view.done || Date.now() > deadline) return view;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// Owner-facing account label guessed from a bank export's filename (ADR-013 pre-fill; the
// owner confirms/edits it before uploading). "Chase5980_Activity_20260719.csv" → "Chase …5980".
export function accountLabelFromFilename(filename: string): string {
  const base = filename.replace(/\.[^.]+$/, "");
  const m = base.match(/^([A-Za-z][A-Za-z ]*?)[ _-]*(\d{3,4})(?!\d)/);
  if (m) return `${m[1].trim()} …${m[2]}`;
  return base.replace(/[_-]+/g, " ").trim();
}

// amountCents (signed) → "$1,234.56" / "-$5.00".
export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const dollars = (Math.abs(cents) / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}$${dollars}`;
}

export function makeApi(apiUrl: string, token: string) {
  const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!res.ok) {
      // The API returns {message} on 4xx; fall back to the status text otherwise.
      const detail = await res.json().catch(() => ({}));
      throw new ApiError(res.status, detail.message ?? `API responded ${res.status}`);
    }
    return (await res.json()) as T;
  };

  return {
    getSettings: () => request<Settings>("/settings"),

    setCadence: (kind: CadenceKind, anchor?: string) =>
      request<Settings>("/settings", {
        method: "PATCH",
        body: JSON.stringify({ cadence: { kind, anchor } }),
      }),

    listCategories: () =>
      request<{ categories: Category[] }>("/categories").then((r) => r.categories),

    createCategory: (name: string) =>
      request<Category>("/categories", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),

    updateCategory: (
      id: string,
      changes: { name?: string; status?: CategoryStatus },
    ) =>
      request<Category>(`/categories/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      }),

    // Ask for a presigned upload URL for one CSV (FR-2.1). The account label travels with
    // the import and every transaction it produces (ADR-013).
    createImport: (filename: string, accountLabel: string) =>
      request<CreatedImport>("/imports", {
        method: "POST",
        body: JSON.stringify({ filename, accountLabel }),
      }),

    // PUT the file straight to S3 via the presigned URL — no Authorization header (the URL is
    // itself the credential) and no JSON wrapper; the file never transits our API (§3.1).
    uploadFile: async (uploadUrl: string, file: Blob): Promise<void> => {
      const res = await fetch(uploadUrl, { method: "PUT", body: file });
      if (!res.ok) throw new ApiError(res.status, `upload failed (${res.status})`);
    },

    getImport: (id: string) =>
      request<ImportSummary>(`/imports/${encodeURIComponent(id)}`),

    listImports: () =>
      request<{ imports: ImportSummary[] }>("/imports").then((r) => r.imports),

    listTransactions: (from?: string, to?: string) => {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const suffix = qs.toString() ? `?${qs}` : "";
      return request<{ transactions: Transaction[]; from: string; to: string }>(
        `/transactions${suffix}`,
      );
    },

    // Cycles available to the picker (FR-5.3), newest first — bounded by the owner's first
    // transaction, so it never offers cycles that predate any data.
    listCycles: () =>
      request<{ cycles: Cycle[]; currentCycleId: string }>("/cycles"),

    // The dashboard read (FR-5.1): budgets + actuals for one cycle, aggregated server-side.
    getCycleSummary: (ref: CycleRef = "current") =>
      request<CycleSummary>(`/cycles/${encodeURIComponent(ref)}/summary`),

    // Set a category's budget for one cycle (FR-4.3); null clears it, because "no budget" is
    // the absence of a target rather than a target of zero.
    setBudget: (ref: CycleRef, categoryId: string, amountCents: number | null) =>
      request<{ cycle: Cycle; budget: { amountCents: number } | null }>(
        `/cycles/${encodeURIComponent(ref)}/budgets/${encodeURIComponent(categoryId)}`,
        { method: "PUT", body: JSON.stringify({ amountCents }) },
      ),

    // Re-drive categorization over a window ([B-7]). Default scope is uncategorized rows only;
    // includeCategorized also re-runs ones the pipeline already filed (never owner decisions).
    recategorize: (from: string, to: string, includeCategorized = false) =>
      request<RecategorizeResult>("/transactions/recategorize", {
        method: "POST",
        body: JSON.stringify({ from, to, includeCategorized }),
      }),

    // --- bank connections (Plaid, dev stage only — these routes 404 where Plaid is off) ---

    listBankConnections: () =>
      request<{ items: BankConnection[] }>("/plaid/items").then((r) => r.items),

    // A Link token for connecting a new bank, or — with itemId — for repairing an existing
    // connection's login (update mode). The server holds the access token; we never do.
    createLinkToken: (itemId?: string) =>
      request<LinkToken>("/plaid/link-token", {
        method: "POST",
        body: JSON.stringify(itemId ? { itemId } : {}),
      }),

    exchangePublicToken: (req: ExchangeRequest) =>
      request<ExchangedConnection>("/plaid/exchange", {
        method: "POST",
        body: JSON.stringify(req),
      }),

    // Start a sync for one connection (or all). Returns import IDs to poll; the work is async.
    syncBank: (itemId?: string) =>
      request<{ imports: { itemId: string; importId: string }[] }>("/plaid/sync", {
        method: "POST",
        body: JSON.stringify(itemId ? { itemId } : {}),
      }),

    // Ends the connection at Plaid and forgets it. Transactions already synced are kept.
    disconnectBank: (itemId: string) =>
      request<{ itemId: string; disconnected: boolean }>(
        `/plaid/items/${encodeURIComponent(itemId)}`,
        { method: "DELETE" },
      ),
  };
}

export type Api = ReturnType<typeof makeApi>;
