import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// Stub the runtime-config and auth seams so the smoke test is deterministic and offline:
// loadConfig never resolves, so the app stays on its initial (logged-out) login screen —
// exactly the state we want to assert renders. This is the runtime coverage the frontend CI
// job lacked (it previously passed on --passWithNoTests, Slice 2).
vi.mock("./config", () => ({
  loadConfig: () => new Promise<never>(() => {}),
}));
vi.mock("./auth", () => ({
  makeUserManager: () => ({}),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  it("renders the login screen", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Ledgerly" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /log in/i })).toBeTruthy();
  });
});
