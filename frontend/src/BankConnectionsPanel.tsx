import { useCallback, useEffect, useRef, useState } from "react";
import {
  usePlaidLink,
  type PlaidLinkError,
  type PlaidLinkOnExitMetadata,
  type PlaidLinkOnSuccessMetadata,
} from "react-plaid-link";
import {
  ApiError,
  formatCents,
  pollImport,
  type Api,
  type BankConnection,
  type ImportSummary,
} from "./api";
import { styles } from "./styles";

// Bank connections (Slice 9, ADR-014 — Plaid Sandbox, dev stage only).
//
// Connect: the server mints a Link token → Plaid Link opens in the page → Link hands back a
// one-time public token → the server exchanges it for an access token it keeps to itself and
// starts the first sync. The browser only ever holds the Link token (briefly) and the public
// token (in transit); it never sees an access token or an API key.
//
// Reconnect (update mode): when a sync fails because the bank login broke, the server mints a
// Link token *for that connection*; the owner logs in again; Link returns no public token, so
// nothing is exchanged — the existing connection simply works again, and a sync confirms it.
//
// Disconnect: the server ends the connection at Plaid (not just in our table — a connection
// left live at Plaid keeps existing and, in Production, keeps being billed). Transactions
// already synced stay, because they are spending history.

// Pending categorization runs behind SQS after a sync; re-read the dashboard after these
// delays so freshly synced rows show up categorized without a manual refresh.
const CATEGORIZE_RELOAD_MS = [20_000, 45_000];

type LinkMode = { mode: "link" } | { mode: "update"; itemId: string };

// One Link token = one Link session. The mode travels with the token so a callback can never
// be interpreted against a different session's mode.
interface LinkSessionState {
  token: string;
  mode: LinkMode;
}

interface SyncOutcome {
  institution: string;
  view: ImportSummary;
}

export function BankConnectionsPanel({
  api,
  onChanged,
  onError,
}: {
  api: Api;
  // Called when transactions may have changed, so the dashboard and list re-read.
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [connections, setConnections] = useState<BankConnection[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [session, setSession] = useState<LinkSessionState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<SyncOutcome[]>([]);

  const timers = useRef<number[]>([]);

  useEffect(
    () => () => {
      timers.current.forEach((t) => window.clearTimeout(t));
    },
    [],
  );

  const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const refresh = useCallback(async () => {
    try {
      setConnections(await api.listBankConnections());
    } catch (e) {
      // 404 = this stage has no Plaid routes (prod): the panel simply isn't offered.
      if (e instanceof ApiError && e.status === 404) setAvailable(false);
      else onError(message(e));
    }
  }, [api, onError]);

  // Pre-initialize Link with a fresh new-connection token, so the button is ready on click.
  const prepareNewLink = useCallback(async () => {
    setSession(null);
    try {
      const { linkToken } = await api.createLinkToken();
      setSession({ token: linkToken, mode: { mode: "link" } });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) onError(message(e));
    }
  }, [api, onError]);

  useEffect(() => {
    refresh();
    prepareNewLink();
  }, [refresh, prepareNewLink]);

  const reloadAfterCategorizing = useCallback(() => {
    onChanged();
    for (const delay of CATEGORIZE_RELOAD_MS) {
      timers.current.push(window.setTimeout(onChanged, delay));
    }
  }, [onChanged]);

  // Start syncs, poll each to completion, and report what they did.
  const runSyncs = useCallback(
    async (itemId?: string) => {
      setBusy("Syncing…");
      setOutcomes([]);
      try {
        const { imports } = await api.syncBank(itemId);
        const names = new Map((connections ?? []).map((c) => [c.itemId, c.institutionName]));
        const results = await Promise.all(
          imports.map(async ({ itemId: id, importId }) => ({
            institution: names.get(id) || "Bank",
            view: await pollImport(api, importId),
          })),
        );
        setOutcomes(results);
        await refresh();
        if (results.some((r) => r.view.added > 0 || (r.view.modified ?? 0) > 0)) {
          reloadAfterCategorizing();
        } else {
          onChanged();
        }
      } catch (e) {
        onError(message(e));
      } finally {
        setBusy(null);
      }
    },
    [api, connections, refresh, onChanged, onError, reloadAfterCategorizing],
  );

  const onSuccess = useCallback(
    async (mode: LinkMode, publicToken: string | null, metadata: PlaidLinkOnSuccessMetadata) => {
      setNotice(null);
      if (mode.mode === "update") {
        // Update mode returns no public token and needs no exchange: the login is repaired
        // in place. A sync both proves it and clears the connection's error.
        setNotice("Reconnected. Syncing…");
        await runSyncs(mode.itemId);
        await prepareNewLink();
        return;
      }
      if (!publicToken) return;
      setBusy("Connecting…");
      try {
        const connected = await api.exchangePublicToken({
          publicToken,
          institution: metadata.institution
            ? { id: metadata.institution.institution_id, name: metadata.institution.name }
            : null,
          linkSessionId: metadata.link_session_id,
        });
        await refresh();
        setBusy("Importing transactions…");
        const view = await pollImport(api, connected.importId);
        setOutcomes([{ institution: connected.institutionName || "Bank", view }]);
        await refresh();
        reloadAfterCategorizing();
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setNotice(`${metadata.institution?.name ?? "That bank"} is already connected.`);
        } else {
          onError(message(e));
        }
      } finally {
        setBusy(null);
        // Link tokens are per session; mint a fresh one for the next connect.
        prepareNewLink();
      }
    },
    [api, refresh, runSyncs, prepareNewLink, onError, reloadAfterCategorizing],
  );

  const onExit = useCallback(
    (mode: LinkMode, error: PlaidLinkError | null, metadata: PlaidLinkOnExitMetadata) => {
      if (error) {
        // display_message is written for end users when present; otherwise use our own copy.
        // The session ID is what Plaid support needs to investigate.
        setNotice(
          error.display_message ??
            `The bank connection didn't complete (${error.error_code}). ` +
              `Try again; if it keeps failing, quote session ${metadata.link_session_id}.`,
        );
      }
      // A plain close (no error) is the owner changing their mind: nothing to report.
      if (mode.mode === "update" || error?.error_code === "INVALID_LINK_TOKEN") {
        prepareNewLink();
      }
    },
    [prepareNewLink],
  );

  const reconnect = async (itemId: string) => {
    setNotice(null);
    try {
      const update = await api.createLinkToken(itemId);
      // The keyed LinkSession below mounts a fresh Link handler for this token and opens it
      // once *that* handler is ready.
      setSession({ token: update.linkToken, mode: { mode: "update", itemId } });
    } catch (e) {
      onError(message(e));
    }
  };

  const disconnect = async (c: BankConnection) => {
    const ok = window.confirm(
      `Disconnect ${c.institutionName || "this bank"}?\n\n` +
        "Ledgerly stops syncing it and the connection is ended at Plaid. " +
        "Transactions already imported stay in Ledgerly.",
    );
    if (!ok) return;
    setBusy("Disconnecting…");
    try {
      await api.disconnectBank(c.itemId);
      setNotice(`${c.institutionName || "Bank"} disconnected.`);
      setOutcomes([]);
      await refresh();
    } catch (e) {
      onError(message(e));
    } finally {
      setBusy(null);
    }
  };

  if (!available) return null;

  const isSandbox = (connections ?? []).some((c) => c.plaidEnv === "sandbox");

  return (
    <section style={styles.card} aria-labelledby="bank-connections-title">
      <h2 id="bank-connections-title" style={styles.sectionTitle}>
        Bank connections{" "}
        {isSandbox && <span style={styles.badge}>Plaid Sandbox</span>}
      </h2>
      <p style={styles.muted}>
        Connect securely through Plaid. Ledgerly never sees your bank login, and you can
        disconnect at any time.
      </p>

      <div style={styles.row}>
        {session ? (
          // Keyed on the token: each Link token gets its own hook instance, so "ready" can only
          // ever mean "this token's handler is loaded" (react-plaid-link keeps the previous
          // handler — and reports ready — while a replacement token is pending).
          <LinkSession
            key={session.token}
            token={session.token}
            autoOpen={session.mode.mode === "update"}
            showConnect={session.mode.mode === "link"}
            disabled={busy !== null}
            onSuccess={(t, m) => onSuccess(session.mode, t, m)}
            onExit={(e, m) => onExit(session.mode, e, m)}
          />
        ) : (
          <button style={styles.button} disabled>
            Connect bank
          </button>
        )}
        <button
          style={styles.buttonGhost}
          onClick={() => runSyncs()}
          disabled={!connections?.length || busy !== null}
        >
          Sync now
        </button>
        {busy && <span style={styles.muted}>{busy}</span>}
      </div>

      {notice && (
        <p role="status" style={{ ...styles.muted, marginTop: 8 }}>
          {notice}
        </p>
      )}

      {outcomes.length > 0 && (
        <ul style={styles.list} aria-label="Sync results">
          {outcomes.map((o, i) => (
            <li key={i} style={styles.summary}>
              <SyncLine institution={o.institution} view={o.view} />
            </li>
          ))}
        </ul>
      )}

      {connections === null ? (
        <p style={styles.muted}>Loading connections…</p>
      ) : connections.length === 0 ? (
        <p style={styles.muted}>No banks connected yet.</p>
      ) : (
        <ul style={styles.list}>
          {connections.map((c) => (
            <li key={c.itemId} style={{ ...styles.listItem, display: "block" }}>
              <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
                <strong style={{ flex: "1 1 auto" }}>{c.institutionName || "Bank"}</strong>
                <span style={styles.muted}>
                  {c.lastSyncedAt ? `Last synced ${relativeTime(c.lastSyncedAt)}` : "Not synced yet"}
                </span>
                {c.needsReconnect && (
                  <button style={styles.button} onClick={() => reconnect(c.itemId)} disabled={busy !== null}>
                    Reconnect
                  </button>
                )}
                <button style={styles.buttonGhost} onClick={() => disconnect(c)} disabled={busy !== null}>
                  Disconnect
                </button>
              </div>
              {c.errorCode && (
                <p role="alert" style={{ ...styles.error, margin: "6px 0 0" }}>
                  {c.needsReconnect
                    ? "The bank needs you to log in again before it can sync. Use Reconnect."
                    : `The last sync failed (${c.errorCode}). Try Sync now again later.`}
                </p>
              )}
              {c.accounts.length > 0 && (
                <ul style={{ ...styles.list, marginTop: 4 }}>
                  {c.accounts.map((a) => (
                    <li key={a.plaidAccountId} style={{ ...styles.muted, display: "flex", gap: 8 }}>
                      <span style={{ flex: "1 1 auto" }}>
                        {a.name}
                        {a.mask && ` ••${a.mask}`}
                        <span style={{ color: "#999" }}> · {a.subtype || a.type}</span>
                      </span>
                      {a.balanceCurrentCents !== null && (
                        <span style={{ fontVariantNumeric: "tabular-nums" }}>
                          {formatCents(a.balanceCurrentCents)}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// One Plaid Link session. Mounted per token (see the key above), so its `ready` is this token's.
function LinkSession({
  token,
  autoOpen,
  showConnect,
  disabled,
  onSuccess,
  onExit,
}: {
  token: string;
  autoOpen: boolean; // update mode: open as soon as ready (the Reconnect click was the gesture)
  showConnect: boolean;
  disabled: boolean;
  onSuccess: (publicToken: string | null, metadata: PlaidLinkOnSuccessMetadata) => void;
  onExit: (error: PlaidLinkError | null, metadata: PlaidLinkOnExitMetadata) => void;
}) {
  const { open, ready } = usePlaidLink({ token, onSuccess, onExit });
  const opened = useRef(false);

  useEffect(() => {
    if (autoOpen && ready && !opened.current) {
      opened.current = true;
      open();
    }
  }, [autoOpen, ready, open]);

  if (!showConnect) {
    return (
      <button style={styles.button} disabled>
        Connect bank
      </button>
    );
  }
  return (
    <button style={styles.button} onClick={() => open()} disabled={!ready || disabled}>
      Connect bank
    </button>
  );
}

function SyncLine({ institution, view }: { institution: string; view: ImportSummary }) {
  if (view.status === "failed") {
    return (
      <span>
        <strong>{institution}</strong>: sync failed — {view.errors[0]?.error ?? "unknown error"}
      </span>
    );
  }
  if (!view.done) {
    return (
      <span>
        <strong>{institution}</strong>: still syncing ({view.status}) — check back shortly.
      </span>
    );
  }
  const parts = [`${view.added} new`];
  if (view.modified) parts.push(`${view.modified} updated`);
  if (view.removed) parts.push(`${view.removed} removed`);
  parts.push(`${view.duplicate} unchanged`);
  return (
    <span>
      <strong>{institution}</strong>: {parts.join(" · ")}
      {view.added > 0 && " — new transactions are being categorized"}
    </span>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
