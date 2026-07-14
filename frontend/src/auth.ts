// Cognito Hosted UI login via Authorization Code + PKCE (architecture §3.5), using
// oidc-client-ts. The OIDC "authority" is the Cognito user-pool issuer, whose discovery
// document points oidc-client-ts at the Hosted UI authorize/token endpoints automatically.

import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { AppConfig } from "./config";

export function makeUserManager(cfg: AppConfig): UserManager {
  const authority = `https://cognito-idp.${cfg.region}.amazonaws.com/${cfg.userPoolId}`;
  return new UserManager({
    authority,
    client_id: cfg.userPoolClientId,
    redirect_uri: cfg.redirectUri,
    post_logout_redirect_uri: cfg.redirectUri,
    response_type: "code", // PKCE is used automatically for public clients
    scope: "openid email profile",
    userStore: new WebStorageStateStore({ store: window.localStorage }),
    automaticSilentRenew: true,
  });
}
