import { afterEach, describe, expect, it, vi } from "vitest";
import { accountLabelFromFilename, ApiError, formatCents, makeApi } from "./api";

// Unit tests for the API client: it must always send the bearer token (identity is derived
// server-side from it, never the body — FR-1.3) and map 4xx bodies to a typed ApiError.
function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("makeApi", () => {
  it("sends the bearer token and parses settings", async () => {
    const fetchMock = mockFetch(200, { type: "PROFILE", cadences: [], currentCycle: {} });
    const api = makeApi("https://api.test", "tok-123");

    await api.getSettings();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/settings");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("PATCHes the cadence with the expected body", async () => {
    const fetchMock = mockFetch(200, { cadences: [], currentCycle: {} });
    const api = makeApi("https://api.test", "tok");

    await api.setCadence("biweekly", "2026-09-04");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/settings");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({
      cadence: { kind: "biweekly", anchor: "2026-09-04" },
    });
  });

  it("unwraps the categories array", async () => {
    mockFetch(200, { categories: [{ categoryId: "1", name: "Coffee", status: "active", sortOrder: 0 }] });
    const api = makeApi("https://api.test", "tok");

    const cats = await api.listCategories();
    expect(cats).toHaveLength(1);
    expect(cats[0].name).toBe("Coffee");
  });

  it("throws a typed ApiError carrying the server message on 4xx", async () => {
    mockFetch(400, { message: "category name must not be empty" });
    const api = makeApi("https://api.test", "tok");

    await expect(api.createCategory("")).rejects.toMatchObject({
      status: 400,
      message: "category name must not be empty",
    });
    await expect(api.createCategory("")).rejects.toBeInstanceOf(ApiError);
  });

  it("creates an import with filename + accountLabel", async () => {
    const fetchMock = mockFetch(201, { importId: "01J", uploadUrl: "https://s3/put" });
    const api = makeApi("https://api.test", "tok");

    await api.createImport("Chase5980.csv", "Chase …5980");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/imports");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      filename: "Chase5980.csv",
      accountLabel: "Chase …5980",
    });
  });

  it("PUTs the file to the presigned URL with no auth header", async () => {
    const fetchMock = mockFetch(200, {});
    const api = makeApi("https://api.test", "tok");
    const blob = new Blob(["a,b\n1,2\n"], { type: "text/csv" });

    await api.uploadFile("https://s3/presigned", blob);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://s3/presigned");
    expect(init.method).toBe("PUT");
    expect(init.headers).toBeUndefined(); // the URL is the credential, not a bearer token
  });

  it("passes from/to as query params to /transactions", async () => {
    const fetchMock = mockFetch(200, { transactions: [], from: "2026-07-01", to: "2026-07-31" });
    const api = makeApi("https://api.test", "tok");

    await api.listTransactions("2026-07-01", "2026-07-31");

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/transactions?from=2026-07-01&to=2026-07-31");
  });

  it("omits the query string when no window is given", async () => {
    const fetchMock = mockFetch(200, { transactions: [], from: "", to: "" });
    const api = makeApi("https://api.test", "tok");

    await api.listTransactions();

    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/transactions");
  });
});

describe("accountLabelFromFilename", () => {
  it("extracts bank + last-4 from a Chase export name", () => {
    expect(accountLabelFromFilename("Chase5980_Activity_20260719.csv")).toBe("Chase …5980");
  });

  it("handles a (1) suffix and keeps the last-4", () => {
    expect(accountLabelFromFilename("Chase5980_Activity_20260719 (1).csv")).toBe("Chase …5980");
  });

  it("falls back to a cleaned base name when no number is present", () => {
    expect(accountLabelFromFilename("my_export.csv")).toBe("my export");
  });
});

describe("formatCents", () => {
  it("formats debits and credits with sign and thousands", () => {
    expect(formatCents(-675)).toBe("-$6.75");
    expect(formatCents(74400)).toBe("$744.00");
    expect(formatCents(-123456)).toBe("-$1,234.56");
    expect(formatCents(0)).toBe("$0.00");
  });
});
