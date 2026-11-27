import { afterEach, describe, expect, it } from "vitest";
import { oauthReturn, rememberLinkSession } from "./plaidOAuth";

const KEY = "ledgerly.plaidLinkSession";
const at = (href: string) => new URL(href) as unknown as Location;
const RETURN = "https://app.example/oauth/plaid?oauth_state_id=abc";

describe("plaidOAuth", () => {
  afterEach(() => localStorage.clear());

  it("resumes a fresh session on the bank's return", () => {
    rememberLinkSession("link-1", { mode: "link" }, 1_000);
    expect(oauthReturn(at(RETURN), 2_000)?.token).toBe("link-1");
  });

  it("forgets a session that is too old to resume", () => {
    rememberLinkSession("link-1", { mode: "link" }, 0);
    expect(oauthReturn(at(RETURN), 2 * 60 * 60 * 1000)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("forgets a session left behind when the page is not a bank return", () => {
    rememberLinkSession("link-1", { mode: "link" }, 1_000);
    expect(oauthReturn(at("https://app.example/"), 2_000)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });
});
