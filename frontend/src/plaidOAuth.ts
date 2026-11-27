// Returning from a bank's own sign-in page (OAuth, ADR-016).
//
// Banks like Chase sign the owner in on their own site. On a desktop Plaid Link does that in a
// popup and nothing here is involved. On a phone it can instead send the whole page to the
// bank, which then comes back to `{site}/oauth/plaid?oauth_state_id=…`. Plaid's rule for that
// return: open Link again with the *same* Link token, plus the full URL the page came back on.
// So the token (short-lived and single-session; never an access token) is kept in
// localStorage for the length of that round trip, and nothing else. localStorage, not
// sessionStorage: a bank's app can hand the owner back in a new tab. It expires after an hour
// and is removed as soon as Link finishes.

export const OAUTH_RETURN_PATH = "/oauth/plaid";
const KEY = "ledgerly.plaidLinkSession";
const MAX_AGE_MS = 60 * 60 * 1000;

export type SavedMode = { mode: "link" } | { mode: "update"; itemId: string };

interface Saved {
  token: string;
  mode: SavedMode;
  savedAt: number;
}

export interface OAuthReturn {
  token: string;
  mode: SavedMode;
  receivedRedirectUri: string;
}

/** Remember the Link session that is about to open, in case the bank's sign-in leaves the page. */
export function rememberLinkSession(token: string, mode: SavedMode, now = Date.now()): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ token, mode, savedAt: now }));
  } catch {
    // Storage blocked: the popup flow still works; only a full-page bank sign-in can't resume.
  }
}

/** The session to resume, if this page load is the bank sending the owner back. */
export function oauthReturn(
  location: Location = window.location,
  now = Date.now(),
): OAuthReturn | null {
  if (location.pathname !== OAUTH_RETURN_PATH) return null;
  if (!new URLSearchParams(location.search).get("oauth_state_id")) return null;
  let saved: unknown;
  try {
    saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
  if (!isSaved(saved) || now - saved.savedAt > MAX_AGE_MS || saved.savedAt > now) return null;
  return { token: saved.token, mode: saved.mode, receivedRedirectUri: location.href };
}

/** Forget the session and put the address bar back on the app's root. */
export function finishOAuthReturn(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // nothing to clean up
  }
  if (window.location.pathname === OAUTH_RETURN_PATH) {
    window.history.replaceState({}, document.title, "/");
  }
}

function isSaved(value: unknown): value is Saved {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const mode = v.mode as Record<string, unknown> | undefined;
  return (
    typeof v.savedAt === "number" &&
    typeof v.token === "string" &&
    v.token.length > 0 &&
    typeof mode === "object" &&
    mode !== null &&
    (mode.mode === "link" || (mode.mode === "update" && typeof mode.itemId === "string"))
  );
}
