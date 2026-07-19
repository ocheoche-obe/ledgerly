import { useEffect, useState } from "react";
import type { User, UserManager } from "oidc-client-ts";
import { loadConfig, type AppConfig } from "./config";
import { makeUserManager } from "./auth";
import { makeApi, type Api, type Category, type Settings } from "./api";
import { SettingsPanel } from "./SettingsPanel";
import { CategoriesPanel } from "./CategoriesPanel";
import { styles } from "./styles";

// Slice 3: budget-cycle settings + category management on the deployed skeleton. After
// Hosted-UI login the app loads the owner's settings (with the live current cycle) and
// categories, then lets them manage both.
export default function App() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [mgr, setMgr] = useState<UserManager | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [api, setApi] = useState<Api | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    Promise.all([client.getSettings(), client.listCategories()])
      .then(([s, c]) => {
        setSettings(s);
        setCategories(c);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [cfg, user]);

  const login = () => mgr?.signinRedirect();
  const logout = () => {
    setSettings(null);
    setCategories(null);
    setApi(null);
    mgr?.signoutRedirect();
  };

  return (
    <main style={styles.main}>
      <h1 style={styles.h1}>Ledgerly</h1>
      <p style={styles.tagline}>Categories &amp; budget cycles — Slice 3</p>

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
        </>
      )}
    </main>
  );
}
