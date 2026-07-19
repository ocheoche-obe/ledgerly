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

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
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
  };
}

export type Api = ReturnType<typeof makeApi>;
