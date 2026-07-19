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
  status: ImportStatus;
  added: number;
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
  balanceCents: number;
  accountId: string;
  descriptionRaw: string;
  merchantNormalized: string;
  categoryId: string | null;
  categoryStatus: string;
  importId: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
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
  };
}

export type Api = ReturnType<typeof makeApi>;
