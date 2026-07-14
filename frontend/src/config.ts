// Runtime configuration, fetched from /config.json (written into the S3 bucket by the
// WebConstruct at deploy time). Keeping it runtime-loaded means the SPA build is
// environment-agnostic — no Cognito/API values are baked into the bundle.

export interface AppConfig {
  region: string;
  userPoolId: string;
  userPoolClientId: string;
  cognitoDomain: string; // hosted UI base URL
  apiUrl: string;
  redirectUri: string;
}

export async function loadConfig(): Promise<AppConfig> {
  const res = await fetch("/config.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load /config.json (${res.status})`);
  }
  return (await res.json()) as AppConfig;
}
