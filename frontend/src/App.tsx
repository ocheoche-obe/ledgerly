import { useEffect, useState } from "react";
import type { User, UserManager } from "oidc-client-ts";
import { loadConfig, type AppConfig } from "./config";
import { makeUserManager } from "./auth";
import {
  makeApi,
  type Api,
  type Category,
  type Settings,
  type Transaction,
} from "./api";
import { DashboardPanel } from "./DashboardPanel";
import { SettingsPanel } from "./SettingsPanel";
import { CategoriesPanel } from "./CategoriesPanel";
import { ImportPanel } from "./ImportPanel";
import { TransactionsPanel } from "./TransactionsPanel";
import { styles } from "./styles";

interface TxnWindow {
  transactions: Transaction[];
  from: string;
  to: string;
}

// Slice 6: the budget dashboard leads the app. After Hosted-UI login the owner sees budget vs.
// actual for the current cycle (FR-5.1) — with a picker for past cycles (FR-5.3) — over the
// transactions that CSV import (Slice 4) and the AI categorizer (Slice 5) produced.
export default function App() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [mgr, setMgr] = useState<UserManager | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [api, setApi] = useState<Api | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [txns, setTxns] = useState<TxnWindow | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped whenever transactions change (import, recategorize) so the dashboard re-reads its
  // cycle summary — the numbers on the core screen must never lag what was just imported.
  const [dataVersion, setDataVersion] = useState(0);

  // 1. Load runtime config and build the auth manager.
  useEffect(() => {
    loadConfig()
      .then((c) => {
        setCfg(c);
        setMgr(makeUserManager(c));
      })
      .catch((e) => setError(String(e)));
  }, []);

  // 2. Complete a redirect callback (if returning from Hosted UI) or restore a session.
  useEffect(() => {
    if (!mgr) return;
    (async () => {
      try {
        if (window.location.search.includes("code=")) {
          const u = await mgr.signinRedirectCallback();
          setUser(u);
          window.history.replaceState({}, document.title, "/");
        } else {
          const u = await mgr.getUser();
          if (u && !u.expired) setUser(u);
        }
      } catch (e) {
        setError(String(e));
      }
    })();
  }, [mgr]);

  // 3. Once signed in, build the API client and load settings + categories.
  useEffect(() => {
    if (!cfg || !user) return;
    const client = makeApi(cfg.apiUrl, user.access_token);
    setApi(client);
    setError(null);
    Promise.all([client.getSettings(), client.listCategories(), client.listTransactions()])
      .then(([s, c, t]) => {
        setSettings(s);
        setCategories(c);
        setTxns(t);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [cfg, user]);

  // Re-fetch the transaction window after a successful import so it shows immediately, and
  // signal the dashboard to re-aggregate.
  const refreshTxns = () => {
    api
      ?.listTransactions()
      .then((t) => {
        setTxns(t);
        setDataVersion((v) => v + 1);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };

  const login = () => mgr?.signinRedirect();
  const logout = () => {
    setSettings(null);
    setCategories(null);
    setTxns(null);
    setApi(null);
    mgr?.signoutRedirect();
  };

  return (
    <main style={styles.main}>
      <h1 style={styles.h1}>Ledgerly</h1>
      <p style={styles.tagline}>Budgets &amp; dashboard — Slice 6</p>

      {error && <pre style={styles.error}>{error}</pre>}

      {!user ? (
        <button style={styles.button} onClick={login} disabled={!mgr}>
          Log in
        </button>
      ) : (
        <>
          <div style={styles.row}>
            <span style={styles.muted}>
              Signed in as <strong>{user.profile.email ?? user.profile.sub}</strong>
            </span>
            <button style={styles.buttonGhost} onClick={logout}>
              Log out
            </button>
          </div>

          {/* The dashboard leads: it is the product's reason to exist (FR-5.1), and the
              question the owner opens the app to answer. */}
          {api && <DashboardPanel api={api} onError={setError} reloadKey={dataVersion} />}

          {api && settings ? (
            <SettingsPanel api={api} settings={settings} onChange={setSettings} onError={setError} />
          ) : (
            <p style={styles.muted}>Loading settings…</p>
          )}

          {api && categories ? (
            <CategoriesPanel
              api={api}
              categories={categories}
              onChange={setCategories}
              onError={setError}
            />
          ) : (
            <p style={styles.muted}>Loading categories…</p>
          )}

          {api && <ImportPanel api={api} onImported={refreshTxns} onError={setError} />}

          {api && txns ? (
            <TransactionsPanel
              api={api}
              transactions={txns.transactions}
              categories={categories ?? []}
              from={txns.from}
              to={txns.to}
              onRecategorized={refreshTxns}
              onError={setError}
            />
          ) : (
            <p style={styles.muted}>Loading transactions…</p>
          )}
        </>
      )}
    </main>
  );
}
