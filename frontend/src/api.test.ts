import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, makeApi } from "./api";

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
});
