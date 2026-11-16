import { describe, expect, it } from "vitest";
import { cognitoLogoutUrl } from "./auth";
import type { AppConfig } from "./config";

const CFG: AppConfig = {
  region: "us-east-1",
  userPoolId: "us-east-1_abc",
  userPoolClientId: "client123",
  cognitoDomain: "https://ledgerly-dev.auth.us-east-1.amazoncognito.com",
  apiUrl: "https://api.example.com",
  redirectUri: "https://app.example.com/",
};

describe("cognitoLogoutUrl", () => {
  it("uses Cognito's own parameter names, not the OIDC ones it rejects", () => {
    const url = new URL(cognitoLogoutUrl(CFG));
    expect(url.origin + url.pathname).toBe("https://ledgerly-dev.auth.us-east-1.amazoncognito.com/logout");
    expect(url.searchParams.get("client_id")).toBe("client123");
    expect(url.searchParams.get("logout_uri")).toBe("https://app.example.com/");
    expect(url.searchParams.has("post_logout_redirect_uri")).toBe(false);
  });
});
