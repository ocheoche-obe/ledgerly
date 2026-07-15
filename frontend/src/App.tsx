import { useEffect, useState, type CSSProperties } from "react";
import type { User, UserManager } from "oidc-client-ts";
import { loadConfig, type AppConfig } from "./config";
import { makeUserManager } from "./auth";

// Walking skeleton (Slice 1): prove the whole stack end-to-end — Hosted UI login, then an
// authenticated GET /settings whose result round-trips from DynamoDB and renders here.
export default function App() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [mgr, setMgr] = useState<UserManager | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [settings, setSettings] = useState<unknown>(null);
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

  const login = () => mgr?.signinRedirect();
  const logout = () => {
    setSettings(null);
    mgr?.signoutRedirect();
  };

  const callSettings = async () => {
    if (!cfg || !user) return;
    setError(null);
    try {
      // Access token in the Authorization header; the API Gateway JWT authorizer verifies it.
      const res = await fetch(`${cfg.apiUrl}/settings`, {
        headers: { Authorization: `Bearer ${user.access_token}` },
      });
      if (!res.ok) throw new Error(`API responded ${res.status}`);
      setSettings(await res.json());
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <main style={styles.main}>
      <h1 style={styles.h1}>Ledgerly</h1>
      <p style={styles.tagline}>Walking skeleton — Slice 1</p>

      {error && <pre style={styles.error}>{error}</pre>}

      {!user ? (
        <button style={styles.button} onClick={login} disabled={!mgr}>
          Log in
        </button>
      ) : (
        <div style={styles.card}>
          <p>
            Signed in as <strong>{user.profile.email ?? user.profile.sub}</strong>
          </p>
          <div style={styles.row}>
            <button style={styles.button} onClick={callSettings}>
              Load my settings
            </button>
            <button style={styles.buttonGhost} onClick={logout}>
              Log out
            </button>
          </div>
          {settings != null && (
            <pre style={styles.result}>{JSON.stringify(settings, null, 2)}</pre>
          )}
        </div>
      )}
    </main>
  );
}

const styles: Record<string, CSSProperties> = {
  main: {
    fontFamily: "system-ui, sans-serif",
    maxWidth: 560,
    margin: "4rem auto",
    padding: "0 1rem",
    lineHeight: 1.5,
  },
  h1: { marginBottom: 0 },
  tagline: { color: "#666", marginTop: 4 },
  card: { border: "1px solid #ddd", borderRadius: 8, padding: "1rem 1.25rem" },
  row: { display: "flex", gap: 12, marginTop: 8 },
  button: {
    padding: "0.5rem 1rem",
    borderRadius: 6,
    border: "none",
    background: "#2563eb",
    color: "white",
    cursor: "pointer",
    fontSize: "1rem",
  },
  buttonGhost: {
    padding: "0.5rem 1rem",
    borderRadius: 6,
    border: "1px solid #ccc",
    background: "white",
    cursor: "pointer",
    fontSize: "1rem",
  },
  result: {
    marginTop: 12,
    background: "#f6f8fa",
    padding: "0.75rem",
    borderRadius: 6,
    overflowX: "auto",
  },
  error: {
    background: "#fef2f2",
    color: "#991b1b",
    padding: "0.75rem",
    borderRadius: 6,
    whiteSpace: "pre-wrap",
  },
};
