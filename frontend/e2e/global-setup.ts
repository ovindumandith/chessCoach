import { request, type FullConfig } from "@playwright/test";

// Sign the admin in ONCE per run and share the token with every test. The backend allows
// only 10 logins per 15 minutes per email+IP, so per-test logins would trip that limit.
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL;
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post("/api/v1/auth/login", {
    data: {
      email: process.env.E2E_ADMIN_EMAIL ?? "admin@chesscoach.local",
      password: process.env.E2E_ADMIN_PASSWORD ?? "admin-pass-for-local-dev",
    },
  });
  if (!res.ok()) {
    throw new Error(
      `Admin login failed (HTTP ${res.status()}): ${await res.text()}. ` +
        "Bootstrap an admin first; HTTP 429 means the login throttle is active (wait 15 minutes).",
    );
  }
  process.env.E2E_ADMIN_TOKEN = (await res.json()).access_token;
  await ctx.dispose();
}
