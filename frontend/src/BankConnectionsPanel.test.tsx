import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlaidLinkOptionsWithLinkToken } from "react-plaid-link";
import { BankConnectionsPanel } from "./BankConnectionsPanel";
import { ApiError, type Api, type BankConnection, type ImportSummary } from "./api";

// Plaid Link itself is a third-party iframe, so it is replaced by a fake hook that records the
// options it was given. Tests then play Link's part by calling onSuccess / onExit directly.
// What matters here: the right server call follows each Link outcome, update mode never
// exchanges a token, and the owner sees what a sync did.

const link = vi.hoisted(() => ({
  options: null as PlaidLinkOptionsWithLinkToken | null,
  open: vi.fn(),
}));

vi.mock("react-plaid-link", () => ({
  usePlaidLink: (options: PlaidLinkOptionsWithLinkToken) => {
    link.options = options;
    return { open: link.open, ready: options.token !== null, error: null, exit: vi.fn(), submit: vi.fn() };
  },
}));

const CONNECTION: BankConnection = {
  itemId: "item-1",
  institutionId: "ins_109508",
  institutionName: "First Platypus Bank",
  accounts: [
    {
      plaidAccountId: "acc-1", accountId: "plaid-checking-0000", name: "Plaid Checking",
      officialName: "", mask: "0000", type: "depository", subtype: "checking",
      balanceCurrentCents: 11000, balanceAvailableCents: 10000, currency: "USD",
    },
  ],
  plaidEnv: "sandbox",
  createdAt: "2026-11-15T22:45:00Z",
  lastSyncedAt: "2026-11-15T22:47:30Z",
  errorCode: "",
  errorAt: "",
  needsReconnect: false,
};

const DONE: ImportSummary = {
  importId: "imp-1", filename: "Plaid sync", accountLabel: "First Platypus Bank", source: "plaid",
  status: "complete", added: 12, modified: 3, removed: 1, duplicate: 0, failed: 0, errors: [],
  createdAt: "", done: true,
};

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    listBankConnections: vi.fn().mockResolvedValue([CONNECTION]),
    createLinkToken: vi.fn().mockImplementation((itemId?: string) =>
      Promise.resolve({
        linkToken: itemId ? "link-update-token" : "link-new-token",
        expiration: "", mode: itemId ? "update" : "link",
      }),
    ),
    exchangePublicToken: vi.fn().mockResolvedValue({ ...CONNECTION, importId: "imp-1" }),
    syncBank: vi.fn().mockResolvedValue({ imports: [{ itemId: "item-1", importId: "imp-1" }] }),
    getImport: vi.fn().mockResolvedValue(DONE),
    disconnectBank: vi.fn().mockResolvedValue({ itemId: "item-1", disconnected: true }),
    ...overrides,
  } as unknown as Api;
}

const SUCCESS_META = {
  institution: { institution_id: "ins_109508", name: "First Platypus Bank" },
  accounts: [],
  link_session_id: "sess-123",
};

beforeEach(() => {
  link.options = null;
  link.open.mockReset();
});
afterEach(cleanup);

describe("BankConnectionsPanel", () => {
  it("lists connected institutions with accounts, balances and last sync", async () => {
    render(<BankConnectionsPanel api={fakeApi()} onChanged={vi.fn()} onError={vi.fn()} />);
    expect(await screen.findByText("First Platypus Bank")).toBeTruthy();
    expect(screen.getByText(/Plaid Checking/)).toBeTruthy();
    expect(screen.getByText("$110.00")).toBeTruthy();
    expect(screen.getByText(/Last synced/)).toBeTruthy();
  });

  it("pre-initializes Link and opens it from the Connect bank button", async () => {
    render(<BankConnectionsPanel api={fakeApi()} onChanged={vi.fn()} onError={vi.fn()} />);
    await waitFor(() => expect(link.options?.token).toBe("link-new-token"));
    const button = screen.getByRole("button", { name: "Connect bank" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    expect(link.open).toHaveBeenCalledOnce();
  });

  it("exchanges the public token with Link's metadata, then reports the first sync", async () => {
    const api = fakeApi();
    const onChanged = vi.fn();
    render(<BankConnectionsPanel api={api} onChanged={onChanged} onError={vi.fn()} />);
    await waitFor(() => expect(link.options?.token).toBe("link-new-token"));

    await act(async () => {
      await link.options!.onSuccess("public-sandbox-abc", SUCCESS_META);
    });

    expect(api.exchangePublicToken).toHaveBeenCalledWith({
      publicToken: "public-sandbox-abc",
      institution: { id: "ins_109508", name: "First Platypus Bank" },
      linkSessionId: "sess-123",
    });
    expect(api.getImport).toHaveBeenCalledWith("imp-1");
    expect(await screen.findByText(/12 new · 3 updated · 1 removed/)).toBeTruthy();
    expect(onChanged).toHaveBeenCalled();
  });

  it("says so when the bank is already connected instead of raising an error", async () => {
    const onError = vi.fn();
    const api = fakeApi({
      exchangePublicToken: vi.fn().mockRejectedValue(new ApiError(409, "already connected")),
    });
    render(<BankConnectionsPanel api={api} onChanged={vi.fn()} onError={onError} />);
    await waitFor(() => expect(link.options?.token).toBe("link-new-token"));
    await act(async () => {
      await link.options!.onSuccess("public-sandbox-abc", SUCCESS_META);
    });
    expect(await screen.findByText("First Platypus Bank is already connected.")).toBeTruthy();
    expect(onError).not.toHaveBeenCalled();
  });

  it("Sync now starts a sync, polls it, and shows what it did", async () => {
    const api = fakeApi();
    render(<BankConnectionsPanel api={api} onChanged={vi.fn()} onError={vi.fn()} />);
    const sync = await screen.findByRole("button", { name: "Sync now" });
    await waitFor(() => expect((sync as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(sync);
    expect(await screen.findByText(/12 new · 3 updated · 1 removed · 0 unchanged/)).toBeTruthy();
    expect(api.syncBank).toHaveBeenCalledWith(undefined);
  });

  it("reconnects a broken login in update mode without exchanging anything", async () => {
    const broken = { ...CONNECTION, errorCode: "ITEM_LOGIN_REQUIRED", needsReconnect: true };
    const api = fakeApi({ listBankConnections: vi.fn().mockResolvedValue([broken]) });
    render(<BankConnectionsPanel api={api} onChanged={vi.fn()} onError={vi.fn()} />);

    expect(await screen.findByText(/log in again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() => expect(api.createLinkToken).toHaveBeenCalledWith("item-1"));
    await waitFor(() => expect(link.options?.token).toBe("link-update-token"));
    await waitFor(() => expect(link.open).toHaveBeenCalled()); // opens once the token is ready

    // Update mode: Link returns no public token.
    await act(async () => {
      await link.options!.onSuccess(null, SUCCESS_META);
    });
    expect(api.exchangePublicToken).not.toHaveBeenCalled();
    expect(api.syncBank).toHaveBeenCalledWith("item-1");
    // ...and the panel goes back to a fresh new-connection token afterwards.
    await waitFor(() => expect(link.options?.token).toBe("link-new-token"));
  });

  it("shows Plaid's display message when Link exits with an error, and nothing on a plain close", async () => {
    render(<BankConnectionsPanel api={fakeApi()} onChanged={vi.fn()} onError={vi.fn()} />);
    await waitFor(() => expect(link.options?.token).toBe("link-new-token"));
    const exitMeta = { institution: null, status: null, link_session_id: "sess-9", request_id: "r" };

    act(() => link.options!.onExit!(null, exitMeta));
    expect(screen.queryByRole("status")).toBeNull();

    act(() =>
      link.options!.onExit!(
        { error_type: "ITEM_ERROR", error_code: "INVALID_CREDENTIALS", error_message: "x",
          display_message: "The credentials were not correct." },
        exitMeta,
      ),
    );
    expect(screen.getByRole("status").textContent).toBe("The credentials were not correct.");
  });

  it("disconnects only after confirmation", async () => {
    const api = fakeApi();
    const confirm = vi.spyOn(window, "confirm");
    render(<BankConnectionsPanel api={api} onChanged={vi.fn()} onError={vi.fn()} />);
    const button = await screen.findByRole("button", { name: "Disconnect" });

    confirm.mockReturnValueOnce(false);
    fireEvent.click(button);
    expect(api.disconnectBank).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(button);
    await waitFor(() => expect(api.disconnectBank).toHaveBeenCalledWith("item-1"));
    expect(confirm.mock.calls[1][0]).toMatch(/Transactions already imported stay/);
    confirm.mockRestore();
  });

  it("hides itself where the bank-connection routes don't exist (prod)", async () => {
    const api = fakeApi({
      listBankConnections: vi.fn().mockRejectedValue(new ApiError(404, "Not Found")),
      createLinkToken: vi.fn().mockRejectedValue(new ApiError(404, "Not Found")),
    });
    const onError = vi.fn();
    const { container } = render(
      <BankConnectionsPanel api={api} onChanged={vi.fn()} onError={onError} />,
    );
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(onError).not.toHaveBeenCalled();
  });
});
