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

/**
 * Cognito's Hosted UI logout URL. Cognito does not implement OIDC RP-initiated logout: its
 * `/logout` wants `client_id` + `logout_uri` (which must be one of the app client's sign-out
 * URLs), not `post_logout_redirect_uri` + `id_token_hint`. oidc-client-ts's `signoutRedirect()`
 * sends the standard names, so Cognito answered "Client does not exist" and kept its own
 * session alive, meaning the next "Log in" signed the same user straight back in.
 */
export function cognitoLogoutUrl(cfg: AppConfig): string {
  const params = new URLSearchParams({ client_id: cfg.userPoolClientId, logout_uri: cfg.redirectUri });
  return `${cfg.cognitoDomain}/logout?${params.toString()}`;
}
