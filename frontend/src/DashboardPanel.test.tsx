import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPanel } from "./DashboardPanel";
import type { Api, CycleSummary } from "./api";

// Renders the core screen against a fake API. The aggregation itself is proven in the backend's
// `test_budgets.py`; what matters here is that the numbers reach the screen intact, that an
// over-budget category is visibly over, and that budget editing sends cents (the units the API
// takes) rather than the dollars the owner types.

const CYCLE = { cycleId: "M#2026-07", kind: "monthly" as const, start: "2026-07-01", end: "2026-07-31" };

const SUMMARY: CycleSummary = {
  cycle: CYCLE,
  perCategory: [
    {
      categoryId: "cat-income", name: "Income", budgetCents: null, spentCents: -250000,
      netCents: 250000, transactionCount: 1, remainingCents: null, over: false, archived: false,
    },
    {
      categoryId: "cat-groc", name: "Groceries", budgetCents: 40000, spentCents: 12500,
      netCents: -12500, transactionCount: 4, remainingCents: 27500, over: false, archived: false,
    },
    {
      categoryId: "cat-dine", name: "Dining Out", budgetCents: 10000, spentCents: 13000,
      netCents: -13000, transactionCount: 6, remainingCents: -3000, over: true, archived: false,
    },
  ],
  totals: {
    moneyInCents: 250000, moneyOutCents: 25500, netCents: 224500, budgetedCents: 50000,
    spentAgainstBudgetCents: 25500, remainingCents: 24500, transactionCount: 11,
    uncategorizedCount: 0,
  },
};

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    listCycles: vi.fn().mockResolvedValue({ cycles: [CYCLE], currentCycleId: CYCLE.cycleId }),
    getCycleSummary: vi.fn().mockResolvedValue(SUMMARY),
    setBudget: vi.fn().mockResolvedValue({ cycle: CYCLE, budget: { amountCents: 45000 } }),
    ...overrides,
  } as unknown as Api;
}

// vitest runs without `globals`, so testing-library's automatic cleanup never registers —
// without this, each render's DOM accumulates and queries match the previous test's rows.
afterEach(cleanup);

describe("DashboardPanel", () => {
  it("shows the cycle, the four totals, and every category", async () => {
    render(<DashboardPanel api={fakeApi()} onError={vi.fn()} reloadKey={0} />);

    expect(await screen.findByRole("heading", { name: /July 2026/ })).toBeTruthy();
    // Money in appears twice — the tile and the Income row — which is the point: the totals
    // band and the category rows are two views of the same money.
    expect(screen.getAllByText("$2,500.00")).toHaveLength(2);
    expect(screen.getByText("$255.00")).toBeTruthy(); // money out (unsigned)
    expect(screen.getByText("$245.00")).toBeTruthy(); // remaining
    expect(screen.getByText("Groceries")).toBeTruthy();
    expect(screen.getByText("Dining Out")).toBeTruthy();
  });

  it("marks an over-budget category as over", async () => {
    render(<DashboardPanel api={fakeApi()} onError={vi.fn()} reloadKey={0} />);

    expect(await screen.findByText(/1 over budget/)).toBeTruthy();
    // -$30.00 remaining is the over-spend the owner has to notice at a glance.
    expect(screen.getByText("-$30.00")).toBeTruthy();
  });

  it("offers a budget control on a category with no target", async () => {
    render(<DashboardPanel api={fakeApi()} onError={vi.fn()} reloadKey={0} />);
    expect(await screen.findByRole("button", { name: "set budget" })).toBeTruthy();
  });

  it("saves a typed dollar amount as cents", async () => {
    const api = fakeApi();
    render(<DashboardPanel api={api} onError={vi.fn()} reloadKey={0} />);

    fireEvent.click(await screen.findByRole("button", { name: /of \$400\.00/ }));
    const input = screen.getByDisplayValue("400.00");
    fireEvent.change(input, { target: { value: "450.50" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(api.setBudget).toHaveBeenCalledWith("current", "cat-groc", 45050),
    );
  });

  it("clearing the field clears the budget rather than setting zero", async () => {
    const api = fakeApi();
    render(<DashboardPanel api={api} onError={vi.fn()} reloadKey={0} />);

    fireEvent.click(await screen.findByRole("button", { name: /of \$400\.00/ }));
    const input = screen.getByDisplayValue("400.00");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(api.setBudget).toHaveBeenCalledWith("current", "cat-groc", null),
    );
  });

  it("flags uncategorized money, which would otherwise be invisible on this screen", async () => {
    const api = fakeApi({
      getCycleSummary: vi.fn().mockResolvedValue({
        ...SUMMARY,
        totals: { ...SUMMARY.totals, uncategorizedCount: 153 },
      }),
    });
    render(<DashboardPanel api={api} onError={vi.fn()} reloadKey={0} />);

    expect(await screen.findByText(/153 transactions are still uncategorized/)).toBeTruthy();
  });
});
